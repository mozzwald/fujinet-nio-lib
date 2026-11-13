        .export _fn_write

        .import __fn_initialized, __fn_sessions
        .import _fn_bbc_rw_setup_write, _fn_bbc_osword78, addysp, return0
        .importzp c_sp, ptr1, ptr2, ptr3, ptr4, tmp1, tmp2, tmp3, tmp4

        .include "fn_protocol.inc"

FN_WRITE_STACK_BYTES              := 10

STACK_LEN                         := 0
STACK_DATA_PTR                    := 2
STACK_OFFSET                      := 4

        .bss
write_block:
        .res    16

        .code

; uint8_t fn_write(fn_handle_t handle,
;                  uint32_t offset,
;                  const uint8_t *data,
;                  uint16_t len,
;                  uint16_t *written)
_fn_write:
        ; Match the common API even when validation fails before ROM access.
        sta     ptr3
        stx     ptr3+1
        ora     ptr3+1
        beq     :+
        lda     #$00
        tay
        sta     (ptr3),y
        iny
        sta     (ptr3),y
:
        lda     ptr3
        ldx     ptr3+1
        ldy     __fn_initialized
        bne     @check_args
        jmp     @invalid

@check_args:
        jsr     _fn_bbc_rw_setup_write
        bcc     @have_session
        cmp     #FN_ERR_NOT_FOUND
        bne     @invalid

@not_found:
        jsr     fix_stack
        ldx     #$00
        lda     #FN_ERR_NOT_FOUND
        rts

@invalid:
        jsr     fix_stack
        ldx     #$00
        lda     #FN_ERR_INVALID
        rts

@have_session:
        ldy     #STACK_OFFSET
        lda     (c_sp),y
        ldy     tmp4
        cmp     __fn_sessions + FN_SESSION_WRITE_OFFSET,y
        bne     @invalid
        ldy     #STACK_OFFSET + 1
        lda     (c_sp),y
        ldy     tmp4
        cmp     __fn_sessions + FN_SESSION_WRITE_OFFSET + 1,y
        bne     @invalid
        ldy     #STACK_OFFSET + 2
        lda     (c_sp),y
        ldy     tmp4
        cmp     __fn_sessions + FN_SESSION_WRITE_OFFSET + 2,y
        bne     @invalid
        ldy     #STACK_OFFSET + 3
        lda     (c_sp),y
        ldy     tmp4
        cmp     __fn_sessions + FN_SESSION_WRITE_OFFSET + 3,y
        bne     @invalid

@get_len:
        ldy     #STACK_LEN
        lda     (c_sp),y
        sta     ptr4
        iny
        lda     (c_sp),y
        sta     ptr4+1
        lda     ptr4
        ora     ptr4+1
        bne     :+
        jmp     @success
:

        ldy     #STACK_DATA_PTR
        lda     (c_sp),y
        sta     ptr2
        iny
        lda     (c_sp),y
        sta     ptr2+1
        lda     ptr2
        ora     ptr2+1
        beq     @invalid

        lda     #$00
        sta     tmp1
        sta     tmp2

        ldy     #15
        tya
@zero_block:
        sta     write_block,y
        dey
        bpl     @zero_block
        lda     #FN_BBC_REASON_WRITE_DATA
        sta     write_block
        lda     tmp3
        sta     write_block + 6

@loop:
        sec
        lda     ptr4
        sbc     tmp1
        sta     ptr1
        lda     ptr4+1
        sbc     tmp2
        tax
        cpx     #$02
        bcc     @use_remaining
        lda     #$00
        sta     write_block + 4
        lda     #$02
        sta     write_block + 5
        bne     @have_chunk

@use_remaining:
        lda     ptr1
        sta     write_block + 4
        txa
        sta     write_block + 5

@have_chunk:
        lda     ptr2
        sta     write_block + 2
        lda     ptr2+1
        sta     write_block + 3

        lda     #<write_block
        ldx     #>write_block
        jsr     _fn_bbc_osword78
        ; The adapter returns status in A, then clears X (changing Z).
        cmp     #$00
        beq     @advance
        cmp     #$03
        bne     :+
        jmp     @not_found
:
        cmp     #$01
        bne     :+
        jmp     @invalid
:
        jsr     fix_stack
        ldx     #$00
        lda     #FN_ERR_IO
        rts

@advance:
        clc
        lda     ptr2
        adc     write_block + 4
        sta     ptr2
        lda     ptr2+1
        adc     write_block + 5
        sta     ptr2+1

        clc
        lda     tmp1
        adc     write_block + 4
        sta     tmp1
        lda     tmp2
        adc     write_block + 5
        sta     tmp2

        ; Each successful ROM chunk advances its cursor. Keep local state
        ; and the caller's confirmed count aligned before the next OSWORD.
        ldy     tmp4
        clc
        lda     __fn_sessions + FN_SESSION_WRITE_OFFSET,y
        adc     write_block + 4
        sta     __fn_sessions + FN_SESSION_WRITE_OFFSET,y
        lda     __fn_sessions + FN_SESSION_WRITE_OFFSET + 1,y
        adc     write_block + 5
        sta     __fn_sessions + FN_SESSION_WRITE_OFFSET + 1,y
        lda     __fn_sessions + FN_SESSION_WRITE_OFFSET + 2,y
        adc     #$00
        sta     __fn_sessions + FN_SESSION_WRITE_OFFSET + 2,y
        lda     __fn_sessions + FN_SESSION_WRITE_OFFSET + 3,y
        adc     #$00
        sta     __fn_sessions + FN_SESSION_WRITE_OFFSET + 3,y

        lda     ptr3
        ora     ptr3+1
        beq     @published
        ldy     #$00
        lda     tmp1
        sta     (ptr3),y
        iny
        lda     tmp2
        sta     (ptr3),y

@published:
        lda     tmp1
        cmp     ptr4
        lda     tmp2
        sbc     ptr4+1
        bcs     :+
        jmp     @loop
:

@success:
        jsr     fix_stack
        jmp     return0

fix_stack:
        ldy     #FN_WRITE_STACK_BYTES
        jmp     addysp
