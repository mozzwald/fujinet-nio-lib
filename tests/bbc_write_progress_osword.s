; Modeled OSWORD adapter: preserve the zero-page locals that the BBC writer
; keeps live across the real MOS call. Only the ROM service is mocked; the
; production writer, setup helper, session lookup and cc65 ABI execute normally.
.export _fn_bbc_osword78
.import _mock_osword78
.importzp ptr2, ptr3, ptr4, tmp1, tmp2, tmp3, tmp4
.bss
argument: .res 2
result: .res 1
.code
_fn_bbc_osword78:
    sta argument
    stx argument+1
    .repeat 2, I
        lda ptr2+I
        pha
        lda ptr3+I
        pha
        lda ptr4+I
        pha
    .endrepeat
    lda tmp1
    pha
    lda tmp2
    pha
    lda tmp3
    pha
    lda tmp4
    pha
    lda argument
    ldx argument+1
    jsr _mock_osword78
    sta result
    pla
    sta tmp4
    pla
    sta tmp3
    pla
    sta tmp2
    pla
    sta tmp1
    .repeat 2, I
        pla
        sta ptr4+1-I
        pla
        sta ptr3+1-I
        pla
        sta ptr2+1-I
    .endrepeat
    ; Match the real adapter: X=0 leaves Z set even for nonzero A.
    lda result
    ldx #0
    rts
