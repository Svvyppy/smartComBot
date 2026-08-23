begin;

create table public.ocr_feedback (
    id uuid primary key default gen_random_uuid(),
    reading_id uuid not null unique
        references public.readings(id) on delete cascade,
    meter_id uuid not null
        references public.meters(id) on delete cascade,
    user_id uuid not null
        references public.users(id) on delete cascade,
    detected_value numeric(18, 6) not null,
    corrected_value numeric(18, 6) not null,
    serial_number text,
    raw_text jsonb not null default '[]'::jsonb,
    mechanical_digits text check (
        mechanical_digits is null or mechanical_digits ~ '^[0-9]+$'
    ),
    photo_path text,
    status text not null default 'pending' check (
        status in ('pending', 'profiled', 'global_fixed', 'ignored')
    ),
    created_at timestamptz not null default now(),
    constraint ck_ocr_feedback_changed check (
        detected_value <> corrected_value
    ),
    constraint ck_ocr_feedback_raw_text_array check (
        jsonb_typeof(raw_text) = 'array'
    )
);

create table public.meter_ocr_profiles (
    meter_id uuid primary key
        references public.meters(id) on delete cascade,
    mechanical_fraction_digits smallint check (
        mechanical_fraction_digits between 0 and 6
    ),
    learned_from_feedback_id uuid
        references public.ocr_feedback(id) on delete set null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index idx_ocr_feedback_user_created
    on public.ocr_feedback(user_id, created_at desc);
create index idx_ocr_feedback_meter_created
    on public.ocr_feedback(meter_id, created_at desc);
create index idx_ocr_feedback_status
    on public.ocr_feedback(status, created_at);

alter table public.ocr_feedback enable row level security;
alter table public.meter_ocr_profiles enable row level security;

grant select, insert, update, delete on table
    public.ocr_feedback,
    public.meter_ocr_profiles
to service_role;

commit;
