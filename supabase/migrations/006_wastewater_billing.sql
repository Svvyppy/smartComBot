begin;

alter table public.tariff_plans
    drop constraint tariff_plans_utility_type_check;

alter table public.tariff_plans
    add constraint tariff_plans_utility_type_check check (
        utility_type in (
            'cold_water',
            'hot_water',
            'wastewater',
            'electricity',
            'gas',
            'heating'
        )
    );

create table public.wastewater_charges (
    id uuid primary key default gen_random_uuid(),
    billing_period_id uuid not null
        references public.billing_periods(id) on delete cascade,
    cold_water_consumption numeric(18, 6) not null
        check (cold_water_consumption >= 0),
    hot_water_consumption numeric(18, 6) not null
        check (hot_water_consumption >= 0),
    consumption numeric(18, 6) not null check (consumption >= 0),
    tariff_price numeric(14, 4) not null check (tariff_price >= 0),
    amount numeric(14, 2) not null check (amount >= 0),
    created_at timestamptz not null default now(),
    constraint uq_wastewater_charges_period unique (billing_period_id),
    constraint ck_wastewater_consumption_sum check (
        consumption = cold_water_consumption + hot_water_consumption
    )
);

alter table public.wastewater_charges enable row level security;

grant select, insert, update, delete
on table public.wastewater_charges
to service_role;

create or replace function public.recalculate_wastewater_charge(
    p_user_id uuid,
    p_billing_period_id uuid,
    p_tariff_price numeric
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_property_id uuid;
    v_cold_water numeric;
    v_hot_water numeric;
    v_charge public.wastewater_charges%rowtype;
begin
    select bp.property_id
      into v_property_id
      from public.billing_periods as bp
      join public.properties as p on p.id = bp.property_id
     where bp.id = p_billing_period_id
       and p.user_id = p_user_id;

    if v_property_id is null then
        raise exception 'billing period not found or access denied' using errcode = '42501';
    end if;
    if p_tariff_price is null or p_tariff_price < 0 then
        raise exception 'invalid wastewater tariff price' using errcode = '22023';
    end if;

    select
        coalesce(sum(c.consumption) filter (where m.type = 'cold_water'), 0),
        coalesce(sum(c.consumption) filter (where m.type = 'hot_water'), 0)
      into v_cold_water, v_hot_water
      from public.charges as c
      join public.meters as m on m.id = c.meter_id
     where c.billing_period_id = p_billing_period_id
       and m.property_id = v_property_id
       and m.type in ('cold_water', 'hot_water');

    insert into public.wastewater_charges (
        billing_period_id,
        cold_water_consumption,
        hot_water_consumption,
        consumption,
        tariff_price,
        amount
    )
    values (
        p_billing_period_id,
        v_cold_water,
        v_hot_water,
        v_cold_water + v_hot_water,
        p_tariff_price,
        round((v_cold_water + v_hot_water) * p_tariff_price, 2)
    )
    on conflict (billing_period_id) do update set
        cold_water_consumption = excluded.cold_water_consumption,
        hot_water_consumption = excluded.hot_water_consumption,
        consumption = excluded.consumption,
        tariff_price = excluded.tariff_price,
        amount = excluded.amount,
        created_at = now()
    returning * into v_charge;

    return to_jsonb(v_charge);
end;
$$;

revoke all on function public.recalculate_wastewater_charge(
    uuid, uuid, numeric
) from public, anon, authenticated;

grant execute on function public.recalculate_wastewater_charge(
    uuid, uuid, numeric
) to service_role;

create or replace function public.record_manual_reading_charge(
    p_user_id uuid,
    p_meter_id uuid,
    p_confirmed_value numeric,
    p_captured_at timestamptz,
    p_year integer,
    p_month integer,
    p_previous_reading numeric,
    p_consumption numeric,
    p_tariff_price numeric,
    p_amount numeric,
    p_wastewater_tariff_price numeric
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_bundle jsonb;
    v_meter_type text;
    v_wastewater_charge jsonb := null;
begin
    select m.type
      into v_meter_type
      from public.meters as m
      join public.properties as p on p.id = m.property_id
     where m.id = p_meter_id
       and p.user_id = p_user_id
       and m.active = true;

    if v_meter_type is null then
        raise exception 'meter not found or access denied' using errcode = '42501';
    end if;
    if v_meter_type in ('cold_water', 'hot_water') then
        if p_wastewater_tariff_price is null or p_wastewater_tariff_price < 0 then
            raise exception 'wastewater tariff is required for water' using errcode = '22023';
        end if;
    elsif p_wastewater_tariff_price is not null then
        raise exception 'wastewater tariff is only valid for water' using errcode = '22023';
    end if;

    v_bundle := public.record_manual_reading_charge(
        p_user_id,
        p_meter_id,
        p_confirmed_value,
        p_captured_at,
        p_year,
        p_month,
        p_previous_reading,
        p_consumption,
        p_tariff_price,
        p_amount
    );

    if v_meter_type in ('cold_water', 'hot_water') then
        v_wastewater_charge := public.recalculate_wastewater_charge(
            p_user_id,
            (v_bundle -> 'billing_period' ->> 'id')::uuid,
            p_wastewater_tariff_price
        );
    end if;

    return v_bundle || jsonb_build_object('wastewater_charge', v_wastewater_charge);
end;
$$;

revoke all on function public.record_manual_reading_charge(
    uuid, uuid, numeric, timestamptz, integer, integer,
    numeric, numeric, numeric, numeric, numeric
) from public, anon, authenticated;

grant execute on function public.record_manual_reading_charge(
    uuid, uuid, numeric, timestamptz, integer, integer,
    numeric, numeric, numeric, numeric, numeric
) to service_role;

create or replace function public.confirm_recognized_reading_charge(
    p_user_id uuid,
    p_reading_id uuid,
    p_confirmed_value numeric,
    p_year integer,
    p_month integer,
    p_previous_reading numeric,
    p_consumption numeric,
    p_tariff_price numeric,
    p_amount numeric,
    p_wastewater_tariff_price numeric
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_bundle jsonb;
    v_meter_type text;
    v_wastewater_charge jsonb := null;
begin
    select m.type
      into v_meter_type
      from public.readings as r
      join public.meters as m on m.id = r.meter_id
      join public.properties as p on p.id = m.property_id
     where r.id = p_reading_id
       and p.user_id = p_user_id
       and m.active = true;

    if v_meter_type is null then
        raise exception 'reading not found or access denied' using errcode = '42501';
    end if;

    v_bundle := public.confirm_recognized_reading_charge(
        p_user_id,
        p_reading_id,
        p_confirmed_value,
        p_year,
        p_month,
        p_previous_reading,
        p_consumption,
        p_tariff_price,
        p_amount
    );

    if v_bundle -> 'billing_period' <> 'null'::jsonb then
        if v_meter_type in ('cold_water', 'hot_water') then
            if p_wastewater_tariff_price is null or p_wastewater_tariff_price < 0 then
                raise exception 'wastewater tariff is required for water'
                    using errcode = '22023';
            end if;
            v_wastewater_charge := public.recalculate_wastewater_charge(
                p_user_id,
                (v_bundle -> 'billing_period' ->> 'id')::uuid,
                p_wastewater_tariff_price
            );
        elsif p_wastewater_tariff_price is not null then
            raise exception 'wastewater tariff is only valid for water'
                using errcode = '22023';
        end if;
    elsif p_wastewater_tariff_price is not null then
        raise exception 'baseline reading cannot contain wastewater tariff'
            using errcode = '22023';
    end if;

    return v_bundle || jsonb_build_object('wastewater_charge', v_wastewater_charge);
end;
$$;

revoke all on function public.confirm_recognized_reading_charge(
    uuid, uuid, numeric, integer, integer,
    numeric, numeric, numeric, numeric, numeric
) from public, anon, authenticated;

grant execute on function public.confirm_recognized_reading_charge(
    uuid, uuid, numeric, integer, integer,
    numeric, numeric, numeric, numeric, numeric
) to service_role;

commit;
