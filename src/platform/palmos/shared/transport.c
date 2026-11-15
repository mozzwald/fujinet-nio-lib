/* Palm-only packet dispatcher: one core, one backend per foreground lifetime. */
#include "private.h"
#include "fn_internal.h"
#include "fn_platform.h"

/* Experimental instrumentation: only RAM counters on the command path.
 * Two TimGetTicks calls per measured operation; no logging or new I/O there.
 * The final diagnostic write is deliberately outside all measured intervals.
 * This Palm-only 72-byte snapshot adds no protocol fields or custom traps. */
#undef PrefGetAppPreferences
#undef PrefSetAppPreferences
static NioTimingExperimental timing;
static Boolean timing_active;

/* All state is Palm A4-owned RAM. One extra snapshot is saved at teardown,
 * never in the command path. The caller's existing exchange clocks delimit
 * capture; existing word-guard clocks delimit the common mapping path. */
NioCS1TimingExperimental nl_cs1_timing;
NioCS1TimingPhase *nl_cs1_timing_current;
UInt16 nl_cs1_timing_active, nl_cs1_map_active;
UInt32 nl_cs1_guard_tick;
static UInt16 cs1_phase;
static UInt32 cs1_phase_start, cs1_exchange_start, cs1_map_start;
static void cs1_profile_reset(UInt32 started, UInt16 ticks)
{
    MemSet(&nl_cs1_timing, sizeof(nl_cs1_timing), 0);
    nl_cs1_timing.size = sizeof(nl_cs1_timing);
    nl_cs1_timing.version = nioCS1TimingVersion;
    nl_cs1_timing.ticksPerSecond = ticks;
    nl_cs1_timing.sampleShift = 6;
    nl_cs1_timing.started = started;
    nl_cs1_timing_active = nl_cs1_map_active = 0;
    nl_cs1_timing_current = NULL;
}
static void cs1_profile_begin(UInt32 tick)
{
    cs1_phase = nioCS1TimingOther;
    nl_cs1_timing_current = &nl_cs1_timing.phase[cs1_phase];
    ++nl_cs1_timing_current->spans;
    cs1_phase_start = cs1_exchange_start = tick;
    nl_cs1_timing_active = 1;
}
UInt16 nl_cs1_profile_set(UInt16 phase)
{
    UInt16 previous = cs1_phase;
    UInt32 now;
    if (!nl_cs1_timing_active || phase == previous) return previous;
    now = TimGetTicks();
    nl_cs1_timing_current->ticks += now - cs1_phase_start;
    cs1_phase = phase;
    nl_cs1_timing_current = &nl_cs1_timing.phase[phase];
    ++nl_cs1_timing_current->spans;
    cs1_phase_start = now;
    return previous;
}
void nl_cs1_profile_phase(UInt16 phase)
{
    nl_cs1_profile_set(phase == nioCS1PhaseWait || phase == nioCS1PhaseResult ?
        nioCS1TimingPoll : phase == nioCS1PhaseReply ? nioCS1TimingReply : nioCS1TimingOther);
}
void nl_cs1_profile_map_begin(UInt32 tick)
{
    if (!nl_cs1_timing_active) return;
    ++nl_cs1_timing_current->mapCalls;
    cs1_map_start = tick;
    nl_cs1_map_active = 1;
}
void nl_cs1_profile_map_end(UInt32 tick)
{
    if (!nl_cs1_map_active) return;
    nl_cs1_timing_current->mapTicks += tick - cs1_map_start;
    nl_cs1_map_active = 0;
}
static void cs1_profile_end(UInt32 tick)
{
    /* A caught card fault closes its interrupted mapping before diagnostics.
     * Defensive closure here also keeps every completed record self-contained. */
    nl_cs1_profile_map_end(tick);
    nl_cs1_timing_current->ticks += tick - cs1_phase_start;
    nl_cs1_timing.exchangeTicks += tick - cs1_exchange_start;
    ++nl_cs1_timing.exchanges;
    nl_cs1_timing_active = 0;
    nl_cs1_timing_current = NULL;
}
static UInt16 timing_bucket(UInt16 id)
{
    return id == 0x4e32 ? 0 : id == 0x4e36 ? 1 : 2;
}
Int16 nl_timing_pref_get(UInt32 creator, UInt16 id, void *data,
                         UInt16 *size, Boolean saved)
{
    UInt32 start, elapsed;
    Int16 result;
    NioTimingBucket *b;
    if (!timing_active) return PrefGetAppPreferences(creator, id, data, size, saved);
    b = &timing.bucket[timing_bucket(id)];
    start = TimGetTicks();
    result = PrefGetAppPreferences(creator, id, data, size, saved);
    elapsed = TimGetTicks() - start;
    b->readTicks += elapsed;
    if (nl_cs1_timing_active) {
        ++nl_cs1_timing_current->prefCalls;
        nl_cs1_timing_current->prefTicks += elapsed;
    }
    ++b->reads;
    return result;
}
void nl_timing_pref_set(UInt32 creator, UInt16 id, Int16 version,
                         void *data, UInt16 size, Boolean saved)
{
    UInt32 start, elapsed;
    NioTimingBucket *b;
    if (!timing_active) {
        PrefSetAppPreferences(creator, id, version, data, size, saved);
        return;
    }
    b = &timing.bucket[timing_bucket(id)];
    start = TimGetTicks();
    PrefSetAppPreferences(creator, id, version, data, size, saved);
    elapsed = TimGetTicks() - start;
    b->writeTicks += elapsed;
    if (nl_cs1_timing_active) {
        ++nl_cs1_timing_current->prefCalls;
        nl_cs1_timing_current->prefTicks += elapsed;
    }
    ++b->writes;
}
static void timing_finish(void)
{
    timing.sessionTicks = TimGetTicks() - timing.started;
    timing_active = false;
    /* No command means no useful benchmark snapshot. Preserve any prior one.
     * Export after normal teardown, outside the timers and recovery decisions. */
    if (timing.exchanges)
        PrefSetAppPreferences(nioLibCreator, nioTimingPref, nioTimingVersion,
                             &timing, sizeof(timing), false);
    if (nl_cs1_timing.exchanges)
        PrefSetAppPreferences(nioLibCreator, nioCS1TimingPref, nioCS1TimingVersion,
                             &nl_cs1_timing, sizeof(nl_cs1_timing), false);
}
#define PrefGetAppPreferences nl_timing_pref_get
#define PrefSetAppPreferences nl_timing_pref_set

#define CONFIG_PREF 0x4e34
static UInt16 active;
static UInt16 last_reply = 0xffff;
void nl_cs1_close(void);
uint8_t nl_cs1_ready(void);
uint8_t nl_cs1_exchange_buffers(const uint8_t *, uint16_t, uint8_t *, uint16_t, uint16_t *);

static void defaults(NioLibConfig *c)
{
    MemSet(c, sizeof(*c), 0);
    c->size = sizeof(*c); c->version = nioConfigVersion;
    c->transport = nioTransportSpringboard; c->serialBaud = 115200UL;
}
Boolean nl_config_valid(const NioLibConfig *c)
{
    return c && c->size == sizeof(*c) && c->version == nioConfigVersion &&
        (c->transport == nioTransportSpringboard || c->transport == nioTransportSerial || c->transport == nioTransportUSB) &&
        !(c->serialOptions & ~nioSerialRTSCTS) &&
        (c->serialBaud == 9600UL || c->serialBaud == 19200UL ||
         c->serialBaud == 38400UL || c->serialBaud == 57600UL || c->serialBaud == 115200UL) &&
        !c->reserved[0] && !c->reserved[1] && !c->reserved[2];
}
UInt16 nl_config_read(NioLibConfig *c)
{
    UInt16 size = sizeof(*c);
    Int16 version;
    defaults(c);
    version = PrefGetAppPreferences(nioLibCreator, CONFIG_PREF, c, &size, true);
    if (version == noPreferenceFound) { defaults(c); return nioConfigDefaulted; }
    if (version != nioConfigVersion || size != sizeof(*c) || !nl_config_valid(c)) {
        defaults(c); return nioConfigInvalid;
    }
    return 0;
}
Err nl_config_write(const NioLibConfig *c)
{
    NioLibConfig check;
    if (!nl_config_valid(c)) return nioLibErrParam;
    PrefSetAppPreferences(nioLibCreator, CONFIG_PREF, nioConfigVersion, (void *)c, sizeof(*c), true);
    if (nl_config_read(&check) || MemCmp(c, &check, sizeof(*c))) return nioLibErrGlobals;
    return errNone;
}
UInt16 nl_selected(void)
{
    NioLibConfig c;
    nl_config_read(&c);
    return c.transport;
}
UInt16 nl_active(void) { return active; }
uint8_t fn_transport_init(void)
{
    NioLibConfig c;
    UInt16 result;
    if (active) return fn_transport_ready() ? FN_OK : FN_ERR_NOT_READY;
    MemSet(&timing, sizeof(timing), 0);
    timing.size = sizeof(timing); timing.version = nioTimingVersion;
    timing.ticksPerSecond = SysTicksPerSecond();
    timing.started = TimGetTicks();
    cs1_profile_reset(timing.started, timing.ticksPerSecond);
    timing_active = true;
    /* Corrupt/unknown saved settings are inspectable as safe defaults, but
     * must not silently open a different backend on the user's behalf. */
    if (nl_config_read(&c) == nioConfigInvalid) return FN_ERR_INVALID;
    timing.transport = c.transport;
    result = c.transport == nioTransportSpringboard ? nl_cs1_open() :
             c.transport == nioTransportSerial ? nl_serial_open(&c) : nl_usb_open();
    if (!result) active = c.transport;
    return result;
}
void fn_transport_close(void)
{
    if (active == nioTransportSpringboard) nl_cs1_close();
    if (active == nioTransportSerial) nl_serial_close();
    if (active == nioTransportUSB) nl_usb_close();
    active = 0;
    if (timing_active) timing_finish();
}
uint8_t fn_transport_ready(void)
{
    if (active == nioTransportSpringboard) return nl_cs1_ready();
    if (active == nioTransportSerial) return nl_serial_ready();
    if (active == nioTransportUSB) return nl_usb_ready();
    return 0;
}
uint8_t fn_transport_exchange_buffers(const uint8_t *request, uint16_t length,
        uint8_t *response, uint16_t capacity, uint16_t *got)
{
    UInt16 result;
    UInt32 exchange_start, exchange_end;
    last_reply = 0xffff;
    if (!got) return FN_ERR_INVALID;
    *got = 0;
    if (!request || !response || length < FN_HEADER_SIZE || length > 1024 || !capacity || capacity > 1024)
        return FN_ERR_INVALID;
    exchange_start = TimGetTicks();
    if (active == nioTransportSpringboard) {
        cs1_profile_begin(exchange_start);
        result = nl_cs1_exchange_buffers(request, length, response, capacity, got);
    } else if (active == nioTransportSerial || active == nioTransportUSB) {
        result = active == nioTransportSerial ?
            nl_serial_exchange(request, length, response, capacity, got) :
            nl_usb_exchange(request, length, response, capacity, got);
        last_reply = result;
    } else return FN_ERR_NOT_READY;
    exchange_end = TimGetTicks();
    if (active == nioTransportSpringboard) cs1_profile_end(exchange_end);
    timing.exchangeTicks += exchange_end - exchange_start;
    ++timing.exchanges;
    return result;
}
uint8_t fn_transport_exchange(void)
{
    return fn_transport_exchange_buffers(_fn_transport_ctx.request, _fn_transport_ctx.req_len,
        _fn_transport_ctx.response, _fn_transport_ctx.resp_max, &_fn_transport_ctx.resp_len);
}
UInt16 nl_transport_begin(void)
{
    return active == nioTransportSpringboard ? nl_cs1_begin() :
           (active == nioTransportSerial || active == nioTransportUSB) ? FN_OK : FN_ERR_NOT_READY;
}
UInt16 nl_transport_probe(UInt16 *host, UInt16 *busy)
{
    NioLibConfig c;
    *host = *busy = 0;
    if (nl_config_read(&c) == nioConfigInvalid) return FN_ERR_INVALID;
    if ((active ? active : c.transport) == nioTransportSpringboard) return nl_cs1_probe(host, busy);
    if ((active ? active : c.transport) == nioTransportUSB)
        return nl_usb_pending() ? FN_ERR_BUSY : nl_usb_available() ? FN_OK : FN_ERR_NOT_FOUND;
    /* Serial manager presence is not proof of a cable or an NIO peer. */
    return nl_serial_pending() ? FN_ERR_BUSY : FN_OK;
}
void nl_transport_retire(void)
{
    if (active == nioTransportSpringboard) nl_cs1_retire();
}
UInt16 nl_transport_pending(void)
{
    return active == nioTransportUSB ? nl_usb_pending() :
           active == nioTransportSerial ? nl_serial_pending() : nl_cs1_pending();
}
UInt16 nl_ambiguous(void)
{
    return active == nioTransportUSB ? nl_usb_pending() :
           active == nioTransportSerial ? nl_serial_pending() : nl_cs1_ambiguous();
}
UInt16 nl_last_result(void)
{
    return active != nioTransportSpringboard ? last_reply : nl_cs1_last_result();
}
void nl_clear_last_result(void) { last_reply = 0xffff; }
Err nl_transport_reset(UInt16 transport)
{
    if (active || nl_usb_owned() || nl_serial_owned()) return nioLibErrBusy;
    if (transport == nioTransportSpringboard) return nl_cs1_reset();
    if (transport == nioTransportSerial) return nl_serial_reset();
    if (transport == nioTransportUSB) return nl_usb_reset();
    return nioLibErrParam;
}
void nl_transport_status(NioLibTransportStatus *s)
{
    NioLibConfig c;
    s->configFlags = nl_config_read(&c);
    s->selected = c.transport; s->active = active;
    s->flags = nioStatusSupported | nioStatusAvailabilityUnknown;
    s->maxPacket = 1024; s->maxSessions = FN_MAX_SESSIONS;
    s->result = s->configFlags == nioConfigInvalid ? FN_ERR_INVALID : FN_OK;
    if (c.transport == nioTransportUSB && !nl_usb_available()) s->result = FN_ERR_NOT_FOUND;
    if (active) s->flags |= nioStatusActive;
    if (active && fn_transport_ready()) s->flags |= nioStatusAvailable;
    if ((c.transport == nioTransportSpringboard && nl_cs1_pending()) ||
        (c.transport == nioTransportSerial && nl_serial_pending()) ||
        (c.transport == nioTransportUSB && nl_usb_pending())) {
        s->flags |= nioStatusRecoveryRequired; s->result = FN_ERR_BUSY;
    }
}
