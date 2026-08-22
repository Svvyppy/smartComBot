begin;

-- users.telegram_id already has a unique btree index from its UNIQUE constraint.
create index ix_properties_user_id on public.properties (user_id);
create index ix_meters_property_id on public.meters (property_id);
create index ix_readings_meter_id on public.readings (meter_id);
create index ix_readings_captured_at on public.readings (captured_at desc);
create index ix_readings_meter_confirmed on public.readings (meter_id, captured_at desc)
    where status in ('confirmed', 'manual') and confirmed_value is not null;
create index ix_tariff_plans_property_id on public.tariff_plans (property_id);
create index ix_tariff_plans_lookup
    on public.tariff_plans (property_id, utility_type, valid_from desc);
create index ix_tariff_rates_plan_id on public.tariff_rates (tariff_plan_id);
create index ix_billing_periods_property_id on public.billing_periods (property_id);
create index ix_charges_billing_period_id on public.charges (billing_period_id);
create index ix_charges_meter_id on public.charges (meter_id);

commit;

