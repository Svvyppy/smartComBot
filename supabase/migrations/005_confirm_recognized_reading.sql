begin;

create or replace function public.confirm_recognized_reading_charge(
    p_user_id uuid,
    p_reading_id uuid,
    p_confirmed_value numeric,
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
    v_latest_value numeric;
    v_reading public.readings%rowtype;
    v_period public.billing_periods%rowtype;
    v_charge public.charges%rowtype;
begin
    select r.*
      into v_reading
      from public.readings as r
      join public.meters as m on m.id = r.meter_id
      join public.properties as p on p.id = m.property_id
     where r.id = p_reading_id
       and p.user_id = p_user_id
       and m.active = true
     for update of r;

    if v_reading.id is null then
        raise exception 'reading not found or access denied' using errcode = '42501';
    end if;
    if v_reading.status <> 'recognized' then
        raise exception 'reading is not awaiting confirmation' using errcode = '55000';
    end if;
    if p_confirmed_value < 0 then
        raise exception 'confirmed value cannot be negative' using errcode = '22023';
    end if;

    select m.property_id
      into v_property_id
      from public.meters as m
     where m.id = v_reading.meter_id;

    select r.confirmed_value
      into v_latest_value
      from public.readings as r
     where r.meter_id = v_reading.meter_id
       and r.id <> v_reading.id
       and r.status in ('confirmed', 'manual')
     order by r.captured_at desc, r.created_at desc
     limit 1;

    if v_latest_value is distinct from p_previous_reading then
        raise exception 'previous reading changed; repeat confirmation' using errcode = '40001';
    end if;

    if p_previous_reading is null then
        if p_year is not null
           or p_month is not null
           or p_consumption is not null
           or p_tariff_price is not null
           or p_amount is not null then
            raise exception 'baseline reading cannot contain billing data' using errcode = '22023';
        end if;

        update public.readings
           set confirmed_value = p_confirmed_value,
               status = 'confirmed'
         where id = p_reading_id
        returning * into v_reading;

        return jsonb_build_object(
            'reading', to_jsonb(v_reading),
            'billing_period', null,
            'charge', null
        );
    end if;

    if p_year is null
       or p_month is null
       or p_consumption is null
       or p_tariff_price is null
       or p_amount is null
       or p_confirmed_value < p_previous_reading
       or p_consumption <> p_confirmed_value - p_previous_reading
       or p_consumption < 0
       or p_tariff_price < 0
       or p_amount < 0 then
        raise exception 'invalid billing snapshot' using errcode = '22023';
    end if;
    if p_month < 1
       or p_month > 12
       or p_year < 2000
       or p_year <> extract(year from v_reading.captured_at)::integer
       or p_month <> extract(month from v_reading.captured_at)::integer then
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

    update public.readings
       set confirmed_value = p_confirmed_value,
           status = 'confirmed'
     where id = p_reading_id
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
        v_reading.meter_id,
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

revoke all on function public.confirm_recognized_reading_charge(
    uuid, uuid, numeric, integer, integer, numeric, numeric, numeric, numeric
) from public, anon, authenticated;

grant execute on function public.confirm_recognized_reading_charge(
    uuid, uuid, numeric, integer, integer, numeric, numeric, numeric, numeric
) to service_role;

commit;
