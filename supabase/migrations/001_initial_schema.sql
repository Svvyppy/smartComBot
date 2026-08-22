begin;

create extension if not exists pgcrypto with schema extensions;

create table public.users (
    id uuid primary key default gen_random_uuid(),
    telegram_id bigint not null unique,
    username text,
    first_name text,
    created_at timestamptz not null default now()
);

create table public.properties (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id) on delete cascade,
    name text not null,
    address text,
    created_at timestamptz not null default now()
);

create table public.meters (
    id uuid primary key default gen_random_uuid(),
    property_id uuid not null references public.properties(id) on delete cascade,
    name text not null,
    type text not null check (
        type in ('cold_water', 'hot_water', 'electricity', 'gas', 'heating')
    ),
    serial_number text,
    unit text not null check (unit in ('m3', 'kwh')),
    active boolean not null default true,
    created_at timestamptz not null default now(),
    constraint uq_meters_property_serial unique (property_id, serial_number)
);

create table public.readings (
    id uuid primary key default gen_random_uuid(),
    meter_id uuid not null references public.meters(id) on delete cascade,
    ocr_value numeric(18, 6),
    confirmed_value numeric(18, 6),
    ocr_confidence real check (
        ocr_confidence is null or (ocr_confidence >= 0 and ocr_confidence <= 1)
    ),
    status text not null check (
        status in ('recognized', 'confirmed', 'rejected', 'manual')
    ),
    photo_path text,
    captured_at timestamptz not null,
    created_at timestamptz not null default now(),
    constraint ck_readings_confirmed_value check (
        status not in ('confirmed', 'manual') or confirmed_value is not null
    )
);

create table public.tariff_plans (
    id uuid primary key default gen_random_uuid(),
    property_id uuid not null references public.properties(id) on delete cascade,
    utility_type text not null check (
        utility_type in ('cold_water', 'hot_water', 'electricity', 'gas', 'heating')
    ),
    name text,
    valid_from date not null,
    valid_to date,
    created_at timestamptz not null default now(),
    constraint ck_tariff_plans_date_range check (
        valid_to is null or valid_to >= valid_from
    )
);

create table public.tariff_rates (
    id uuid primary key default gen_random_uuid(),
    tariff_plan_id uuid not null references public.tariff_plans(id) on delete cascade,
    zone text not null default 'standard' check (
        zone in ('standard', 'day', 'night', 't1', 't2', 't3')
    ),
    min_consumption numeric(18, 6),
    max_consumption numeric(18, 6),
    price numeric(14, 4) not null check (price >= 0),
    constraint ck_tariff_rates_consumption_range check (
        max_consumption is null
        or min_consumption is null
        or max_consumption > min_consumption
    )
);

create table public.billing_periods (
    id uuid primary key default gen_random_uuid(),
    property_id uuid not null references public.properties(id) on delete cascade,
    year integer not null check (year >= 2000),
    month integer not null check (month between 1 and 12),
    status text not null default 'open' check (status in ('open', 'closed')),
    created_at timestamptz not null default now(),
    constraint uq_billing_period_property_month unique (property_id, year, month)
);

create table public.charges (
    id uuid primary key default gen_random_uuid(),
    billing_period_id uuid not null references public.billing_periods(id) on delete cascade,
    meter_id uuid not null references public.meters(id) on delete restrict,
    previous_reading numeric(18, 6) not null,
    current_reading numeric(18, 6) not null,
    consumption numeric(18, 6) not null check (consumption >= 0),
    tariff_price numeric(14, 4) not null check (tariff_price >= 0),
    amount numeric(14, 2) not null check (amount >= 0),
    created_at timestamptz not null default now(),
    constraint ck_charges_reading_order check (current_reading >= previous_reading),
    constraint uq_charges_period_meter unique (billing_period_id, meter_id)
);

-- No anon/authenticated policies are created. The trusted Raspberry Pi backend uses
-- the service_role key, while RLS denies direct public Data API access by default.
alter table public.users enable row level security;
alter table public.properties enable row level security;
alter table public.meters enable row level security;
alter table public.readings enable row level security;
alter table public.tariff_plans enable row level security;
alter table public.tariff_rates enable row level security;
alter table public.billing_periods enable row level security;
alter table public.charges enable row level security;

grant select, insert, update, delete on table
    public.users,
    public.properties,
    public.meters,
    public.readings,
    public.tariff_plans,
    public.tariff_rates,
    public.billing_periods,
    public.charges
to service_role;

commit;

