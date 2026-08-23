begin;

alter table public.charges
    drop constraint charges_meter_id_fkey;

alter table public.charges
    add constraint charges_meter_id_fkey
    foreign key (meter_id)
    references public.meters(id)
    on delete cascade;

commit;
