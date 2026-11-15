/* Midpoint-linked Palm-only certificate owner: reachable by early Close and
 * late CS1 access/fault handlers without widening signed DISP16 calls.
 * Scalar A4 RAM only; no caller pointer, heap, packet or recovery storage. */
#include "private.h"

#if NL_CS1_PAYLOAD_WORDS
UInt32 nl_payload_base, nl_payload_next, nl_payload_limit;
UInt16 nl_payload_left;
Boolean nl_payload_active;

void nl_cs1_payload_cancel(void)
{
    nl_payload_active = false;
    nl_payload_left = 0;
    nl_payload_base = nl_payload_next = nl_payload_limit = 0;
}
#endif
