/* A libudev that enumerates nothing.
 *
 * Vivado 2022.2's licence manager (libXil_lmgr11.so) dlopens libudev.so.1 and
 * walks every device on the machine to build a host fingerprint for WebTalk
 * registration. Inside a container that walk aborts the build:
 *
 *     realloc(): invalid pointer
 *     Abnormal program termination (6)
 *
 * By then Vivado's bundled tcmalloc has replaced malloc process-wide, while
 * libudev still frees through glibc. The two allocators disagree and glibc's
 * heap checker - correctly - kills the process. The crash lands in synthesis
 * with a stack that names neither udev nor licensing near the top.
 *
 * Suppressing the check (MALLOC_CHECK_ and friends) would hide real heap
 * corruption inside the tool that produces the bitstream, which is not a
 * trade worth making. Instead this stub answers the enumeration with an empty
 * list. It allocates nothing and frees nothing, so there are no allocators to
 * disagree, and the licence manager falls back to its other host-id sources.
 *
 * Only the fingerprint is affected. Synthesis, implementation and the
 * bitstream are untouched - and nothing here needs a licence anyway: the
 * XC7Z020 is a WebPACK part.
 *
 * These are the 20 symbols libXil_lmgr11.so resolves by name; there is no
 * udev_enumerate_add_match_*, which is why it scans the whole system.
 */
static int udev_stub_handle;
#define HANDLE ((void *)&udev_stub_handle)

void *udev_new(void)                              { return HANDLE; }
void *udev_unref(void *u)                         { (void)u; return 0; }
void *udev_enumerate_new(void *u)                 { (void)u; return HANDLE; }
int   udev_enumerate_scan_devices(void *e)        { (void)e; return 0; }
/* The empty list. Every caller loop below this exits immediately. */
void *udev_enumerate_get_list_entry(void *e)      { (void)e; return 0; }
void *udev_enumerate_unref(void *e)               { (void)e; return 0; }

void *udev_list_entry_get_next(void *l)           { (void)l; return 0; }
const char *udev_list_entry_get_name(void *l)     { (void)l; return 0; }
const char *udev_list_entry_get_value(void *l)    { (void)l; return 0; }

void *udev_device_new_from_syspath(void *u, const char *p) { (void)u; (void)p; return 0; }
void *udev_device_unref(void *d)                  { (void)d; return 0; }
const char *udev_device_get_devnode(void *d)      { (void)d; return 0; }
const char *udev_device_get_devpath(void *d)      { (void)d; return 0; }
const char *udev_device_get_devtype(void *d)      { (void)d; return 0; }
const char *udev_device_get_subsystem(void *d)    { (void)d; return 0; }
const char *udev_device_get_sysname(void *d)      { (void)d; return 0; }
const char *udev_device_get_sysnum(void *d)       { (void)d; return 0; }
const char *udev_device_get_syspath(void *d)      { (void)d; return 0; }
void *udev_device_get_devlinks_list_entry(void *d)   { (void)d; return 0; }
void *udev_device_get_properties_list_entry(void *d) { (void)d; return 0; }
