#ifndef NL_SHARED_PRIVATE_H
#define NL_SHARED_PRIVATE_H
#include <PalmOS.h>
#include "fujinet-nio.h"
#include "NioLib.h"
#include "NioLibCS1Diagnostic.h"
#include "NioLibTimingExperimental.h"

/* Experimental wrappers preserve arguments, results and preference ordering. */
Int16 nl_timing_pref_get(UInt32, UInt16, void *, UInt16 *, Boolean);
void nl_timing_pref_set(UInt32, UInt16, Int16, void *, UInt16, Boolean);
#define PrefGetAppPreferences nl_timing_pref_get
#define PrefSetAppPreferences nl_timing_pref_set

/* Experimental CS1 accounting. No timers are inserted between the final
 * deadline check and MMIO. Word samples reuse that existing guard timestamp;
 * feature/attribute samples bracket only every 64th existing OS operation. */
extern NioCS1TimingExperimental nl_cs1_timing;
extern NioCS1TimingPhase *nl_cs1_timing_current;
extern UInt16 nl_cs1_timing_active, nl_cs1_map_active;
extern UInt32 nl_cs1_guard_tick;
void nl_cs1_profile_phase(UInt16 diagnosticPhase);
UInt16 nl_cs1_profile_set(UInt16 phase);
void nl_cs1_profile_map_begin(UInt32 tick);
void nl_cs1_profile_map_end(UInt32 tick);
#define NL_CS1_SAMPLE_BEGIN(counter, sampled, tick) do { \
    (sampled) = false; \
    if (nl_cs1_timing_active) { \
        ++(counter).calls; \
        (sampled) = !((counter).calls & nioCS1TimingSampleMask); \
        if (sampled) (tick) = TimGetTicks(); \
    } \
} while (0)
#define NL_CS1_WORD_BEGIN(counter, sampled, tick) do { \
    (sampled) = false; \
    if (nl_cs1_timing_active) { \
        ++(counter).calls; \
        (sampled) = !((counter).calls & nioCS1TimingSampleMask); \
        (tick) = nl_cs1_guard_tick; \
    } \
} while (0)
#define NL_CS1_SAMPLE_END(counter, sampled, tick) do { \
    if (sampled) { \
        (counter).ticks += TimGetTicks() - (tick); \
        ++(counter).samples; \
    } \
} while (0)

/* Shared-only hooks: the default static Palm build remains unchanged. */
UInt16 nl_bus_read(UInt32 address);
void nl_bus_write(UInt32 address, UInt16 value);
Err nl_card_attr(UInt16 card, UInt16 attr, void *value);
int nl_expired(UInt32 start, UInt32 wait);
int nl_cs1_expired(UInt32 start, UInt32 wait);
void nl_deadline(UInt16 milliseconds);
UInt16 nl_transport_probe(UInt16 *hostP, UInt16 *busyP);
UInt16 nl_transport_begin(void);
UInt16 nl_transport_pending(void);
void nl_transport_retire(void);
UInt16 nl_last_result(void);
void nl_clear_last_result(void);
Err nl_transport_reset(UInt16 transport);
Err nl_cs1_reset(void);
Err nl_serial_reset(void);
Err nl_usb_reset(void);
UInt16 nl_ambiguous(void);
Err nl_can_close(void);
Boolean nl_client_idle(void);
UInt16 nl_config_read(NioLibConfig *config);
Boolean nl_config_valid(const NioLibConfig *config);
Err nl_config_write(const NioLibConfig *config);
UInt16 nl_selected(void);
UInt16 nl_active(void);
void nl_transport_status(NioLibTransportStatus *status);
UInt16 nl_cs1_open(void);
UInt16 nl_cs1_probe(UInt16 *, UInt16 *);
UInt16 nl_cs1_begin(void);
UInt16 nl_cs1_pending(void);
void nl_cs1_retire(void);
extern NioLibCS1Diagnostic nl_cs1_diag;
extern NioLibCS1Samples nl_cs1_samples;
void nl_cs1_diagnostic_begin(void);
UInt16 nl_cs1_guard_result(void);
Boolean nl_cs1_reply_valid(const UInt8 *, const UInt8 *, UInt16, UInt16, UInt16);
UInt16 nl_cs1_last_result(void);
UInt16 nl_cs1_ambiguous(void);
UInt16 nl_serial_open(const NioLibConfig *);
void nl_serial_close(void);
UInt16 nl_serial_ready(void);
UInt16 nl_serial_owned(void);
UInt16 nl_serial_pending(void);
UInt16 nl_serial_exchange(const UInt8 *, UInt16, UInt8 *, UInt16, UInt16 *);
UInt16 nl_usb_open(void);
void nl_usb_close(void);
UInt16 nl_usb_ready(void);
UInt16 nl_usb_pending(void);
UInt16 nl_usb_owned(void);
UInt16 nl_usb_available(void);
UInt16 nl_usb_exchange(const UInt8 *, UInt16, UInt8 *, UInt16, UInt16 *);
void nl_note_open_failure(UInt16 result);
UInt16 nl_json_query(UInt16 handle, const Char *selector);
Boolean nl_payload_valid(const UInt8 *, const UInt8 *, UInt16, UInt16);

#ifdef FN_PALMOS_SHARED
#define FN_PALMOS_CARD_ATTR_GET nl_card_attr
#define FN_PALMOS_EXPIRED(start, wait) nl_cs1_expired((start), (wait))
#endif
#endif
