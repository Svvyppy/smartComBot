begin;

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
    p_amount numeric
)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_property_id uuid;
    v_period public.billing_periods%rowtype;
    v_reading public.readings%rowtype;
    v_charge public.charges%rowtype;
begin
    select m.property_id
      into v_property_id
      from public.meters as m
      join public.properties as p on p.id = m.property_id
     where m.id = p_meter_id
       and p.user_id = p_user_id
       and m.active = true;

    if v_property_id is null then
        raise exception 'meter not found or access denied' using errcode = '42501';
    end if;
    if p_confirmed_value < p_previous_reading
       or p_consumption <> p_confirmed_value - p_previous_reading
       or p_consumption < 0
       or p_tariff_price < 0
       or p_amount < 0 then
        raise exception 'invalid billing snapshot' using errcode = '22023';
    end if;
    if p_month < 1
       or p_month > 12
       or p_year < 2000
       or p_year <> extract(year from p_captured_at)::integer
       or p_month <> extract(month from p_captured_at)::integer then
        raise exception 'invalid billing period' using errcode = '22023';
    end if;

    insert into public.billing_periods (property_id, year, month)
    values (v_property_id, p_year, p_month)
    on conflict (property_id, year, month) do update
        set status = billing_periods.status
    returning * into v_period;

    if v_period.status = 'closed' then
        raise exception 'billing period is closed' using errcode = '55000';
    end if;

    insert into public.readings (
        meter_id,
        confirmed_value,
        status,
        captured_at
    )
    values (
        p_meter_id,
        p_confirmed_value,
        'manual',
        p_captured_at
    )
    returning * into v_reading;

    insert into public.charges (
        billing_period_id,
        meter_id,
        previous_reading,
        current_reading,
        consumption,
        tariff_price,
        amount
    )
    values (
        v_period.id,
        p_meter_id,
        p_previous_reading,
        p_confirmed_value,
        p_consumption,
        p_tariff_price,
        p_amount
    )
    on conflict (billing_period_id, meter_id) do update set
        previous_reading = excluded.previous_reading,
        current_reading = excluded.current_reading,
        consumption = excluded.consumption,
        tariff_price = excluded.tariff_price,
        amount = excluded.amount,
        created_at = now()
    returning * into v_charge;

    return jsonb_build_object(
        'reading', to_jsonb(v_reading),
        'billing_period', to_jsonb(v_period),
        'charge', to_jsonb(v_charge)
    );
end;
$$;

revoke all on function public.record_manual_reading_charge(
    uuid, uuid, numeric, timestamptz, integer, integer,
    numeric, numeric, numeric, numeric
) from public, anon, authenticated;

grant execute on function public.record_manual_reading_charge(
    uuid, uuid, numeric, timestamptz, integer, integer,
    numeric, numeric, numeric, numeric
) to service_role;

commit;
