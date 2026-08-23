begin;

alter table public.ocr_feedback
    add column corrected_serial_number text;

alter table public.ocr_feedback
    drop constraint ck_ocr_feedback_changed;

alter table public.ocr_feedback
    add constraint ck_ocr_feedback_changed check (
        detected_value <> corrected_value
        or corrected_serial_number is distinct from serial_number
    );

commit;
