// SPDX-License-Identifier: GPL-2.0
/* Test exact userspace mappings, page contents, mprotect and fork/COW. */
#define _GNU_SOURCE
#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

/* Linux UAPI value, also when building against older libc headers. */
#ifndef MAP_FIXED_NOREPLACE
#define MAP_FIXED_NOREPLACE 0x100000
#endif

#define VA39_TOP (UINT64_C(1) << 39)
#define VA40_TOP (UINT64_C(1) << 40)
#define VA48_TOP (UINT64_C(1) << 48)
#define TEST_PAGES 64U

static size_t page_size;

static int fail_errno(const char *label)
{
	int saved_errno = errno;

	fprintf(stderr, "%s FAILED: errno=%d (%s)\n", label,
		saved_errno, strerror(saved_errno));
	return -1;
}

static int unmap_region(void *p, size_t len)
{
	if (munmap(p, len) != 0)
		return fail_errno("munmap");
	return 0;
}

static void *map_region(const char *label, uint64_t address, size_t len,
			int exact)
{
	int flags = MAP_PRIVATE | MAP_ANONYMOUS;
	void *p;

	if (exact)
		flags |= MAP_FIXED_NOREPLACE;
	p = mmap((void *)(uintptr_t)address, len, PROT_READ | PROT_WRITE,
		 flags, -1, 0);
	if (p == MAP_FAILED) {
		fail_errno(label);
		return MAP_FAILED;
	}
	/* Old kernels can ignore MAP_FIXED_NOREPLACE and treat this as a hint. */
	if (exact && (uint64_t)(uintptr_t)p != address) {
		fprintf(stderr,
			"%s FAILED: requested=%#" PRIx64 " returned=%#" PRIxPTR
			"; MAP_FIXED_NOREPLACE was not honored\n",
			label, address, (uintptr_t)p);
		unmap_region(p, len);
		return MAP_FAILED;
	}
	return p;
}

/* Each of the 64 pages gets a distinct nonzero byte in every generation. */
static uint8_t pattern(size_t page, unsigned int generation)
{
	return (uint8_t)((page + generation * 67U) % 255U + 1U);
}

static void fill_pages(void *p, unsigned int generation)
{
	uint8_t *q = p;
	size_t page;

	for (page = 0; page < TEST_PAGES; page++)
		memset(q + page * page_size, pattern(page, generation), page_size);
}

static int check_pages(const char *label, const void *p,
		       unsigned int generation)
{
	const volatile uint8_t *q = p;
	size_t page, byte;

	for (page = 0; page < TEST_PAGES; page++) {
		uint8_t expected = pattern(page, generation);

		for (byte = 0; byte < page_size; byte++) {
			size_t offset = page * page_size + byte;
			uint8_t actual = q[offset];

			if (actual != expected) {
				fprintf(stderr,
					"%s FAILED: offset=%zu expected=%#x actual=%#x\n",
					label, offset, (unsigned int)expected,
					(unsigned int)actual);
				return -1;
			}
		}
	}
	return 0;
}

static int try_mapping(const char *label, uint64_t address, size_t len,
		       int exact)
{
	void *p = map_region(label, address, len, exact);
	int result;

	if (p == MAP_FAILED)
		return -1;
	fill_pages(p, 0);
	result = check_pages(label, p, 0);
	if (result == 0)
		printf("%-30s OK [%#" PRIxPTR ", %#" PRIx64 ") len=%zu\n",
		       label, (uintptr_t)p, (uint64_t)(uintptr_t)p + len, len);
	if (unmap_region(p, len) != 0)
		result = -1;
	return result;
}

static int test_cow(size_t len)
{
	void *p = map_region("high mapping for COW", VA40_TOP + (UINT64_C(64) << 20),
			     len, 1);
	pid_t child, waited;
	int status, result = -1;

	if (p == MAP_FAILED)
		return -1;
	fill_pages(p, 0);
	if (check_pages("parent initial contents", p, 0) != 0)
		goto out;
	if (mprotect(p, len, PROT_READ) != 0) {
		fail_errno("parent mprotect read-only");
		goto out;
	}
	if (check_pages("parent read-only contents", p, 0) != 0)
		goto out;
	if (fflush(NULL) != 0) {
		fail_errno("fflush before fork");
		goto out;
	}
	child = fork();
	if (child < 0) {
		fail_errno("fork");
		goto out;
	}
	if (child == 0) {
		/* Bound a broken child; the parent checks signal termination too. */
		alarm(15);
		if (check_pages("child inherited contents", p, 0) != 0)
			_exit(2);
		if (mprotect(p, len, PROT_READ | PROT_WRITE) != 0) {
			fail_errno("child mprotect read-write");
			_exit(3);
		}
		fill_pages(p, 1);
		if (check_pages("child modified contents", p, 1) != 0)
			_exit(4);
		if (unmap_region(p, len) != 0)
			_exit(5);
		_exit(0);
	}
	do {
		waited = waitpid(child, &status, 0);
	} while (waited < 0 && errno == EINTR);
	if (waited < 0) {
		fail_errno("waitpid");
		goto out;
	}
	if (waited != child || !WIFEXITED(status) || WEXITSTATUS(status) != 0) {
		fprintf(stderr, "fork/COW FAILED: pid=%ld waitpid=%ld status=%#x\n",
			(long)child, (long)waited, status);
		goto out;
	}
	/* Child wrote every page; the parent's private mapping must be unchanged. */
	if (check_pages("parent unchanged after child writes", p, 0) != 0)
		goto out;
	if (mprotect(p, len, PROT_READ | PROT_WRITE) != 0) {
		fail_errno("parent mprotect read-write");
		goto out;
	}
	fill_pages(p, 2);
	if (check_pages("parent writes after COW", p, 2) != 0)
		goto out;
	printf("high mapping fork/mprotect/COW OK\n");
	result = 0;
out:
	if (unmap_region(p, len) != 0)
		result = -1;
	return result;
}

int main(void)
{
	long system_page_size;
	size_t len;
	unsigned int failures = 0;

	if (setvbuf(stdout, NULL, _IOLBF, 0) != 0) {
		fprintf(stderr, "cannot configure stdout buffering\n");
		return EXIT_FAILURE;
	}
	if (sizeof(void *) != 8 || sizeof(uintptr_t) != 8) {
		fprintf(stderr, "FAILED: a 64-bit userspace executable is required\n");
		return EXIT_FAILURE;
	}
	system_page_size = sysconf(_SC_PAGESIZE);
	if (system_page_size <= 0 ||
	    (uintmax_t)system_page_size > SIZE_MAX / TEST_PAGES) {
		fprintf(stderr, "FAILED: invalid system page size %ld\n", system_page_size);
		return EXIT_FAILURE;
	}
	page_size = (size_t)system_page_size;
	if ((page_size & (page_size - 1)) != 0 ||
	    page_size > VA39_TOP / TEST_PAGES) {
		fprintf(stderr, "FAILED: unsupported system page size %zu\n", page_size);
		return EXIT_FAILURE;
	}
	len = TEST_PAGES * page_size;
	printf("userspace bits=%zu page=%zu pages per mapping=%u\n",
	       sizeof(void *) * 8, page_size, TEST_PAGES);
	failures += try_mapping("default mmap", 0, len, 0) != 0;
	failures += try_mapping("just below 2^39", VA39_TOP - len, len, 1) != 0;
	failures += try_mapping("crosses 2^39", VA39_TOP - len / 2, len, 1) != 0;
	failures += try_mapping("crosses 2^40", VA40_TOP - len / 2, len, 1) != 0;
	failures += try_mapping("ends at 2^48", VA48_TOP - len, len, 1) != 0;
	failures += test_cow(len) != 0;
	if (failures != 0) {
		fprintf(stderr, "FAILED: %u required test(s) failed\n", failures);
		return EXIT_FAILURE;
	}
	printf("PASS: all required mapping and COW checks passed on this system\n");
	return EXIT_SUCCESS;
}
