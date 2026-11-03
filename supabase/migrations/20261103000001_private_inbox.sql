-- Private inboxes. A connected mailbox, and everything read from it (emails, attachments, review items, email
-- sorting feedback), is visible only to the person who connected it and the people they choose.
-- This is enforced by Row Level Security, so it holds for every screen and API call, not just the menu.
-- Workspace owners/admins can see that a mailbox is connected (address and status) but not its email, unless
-- they're given access. The platform owner's cross-workspace access does NOT extend to anyone's email.

create table if not exists public.mailbox_access (
    tenant_id        uuid not null references public.tenants(id) on delete cascade,
    mail_account_id  uuid not null references public.mail_accounts(id) on delete cascade,
    user_id          uuid not null references public.profiles(id) on delete cascade,
    granted_by       uuid references public.profiles(id) on delete set null,
    created_at       timestamptz not null default now(),
    primary key (mail_account_id, user_id)
);

-- A mailbox connected before this change belongs to whoever connected it; if that wasn't recorded,
-- to the workspace's first owner.
update public.mail_accounts ma set user_id = (
    select m.user_id from public.memberships m where m.tenant_id = ma.tenant_id and m.role = 'owner'
    order by m.created_at limit 1)
where ma.user_id is null;

-- Membership only: no platform-admin shortcut, unlike is_member().
create or replace function public.is_member_strict(t uuid) returns boolean
language sql stable security definer set search_path = public as $$
    select exists (select 1 from public.memberships m where m.tenant_id = t and m.user_id = auth.uid());
$$;

create or replace function public.can_read_mailbox(acct uuid) returns boolean
language sql stable security definer set search_path = public as $$
    select exists (
        select 1 from public.mail_accounts ma
        where ma.id = acct and public.is_member_strict(ma.tenant_id)
          and (ma.user_id = auth.uid()
               or exists (select 1 from public.mailbox_access x where x.mail_account_id = ma.id and x.user_id = auth.uid())));
$$;

create or replace function public.can_read_email(e uuid) returns boolean
language sql stable security definer set search_path = public as $$
    select public.can_read_mailbox((select mail_account_id from public.email_messages where id = e));
$$;

-- Does this person have any inbox in this workspace? (Decides whether the Inbox tab shows.)
create or replace function public.has_inbox_access(t uuid) returns boolean
language sql stable security definer set search_path = public as $$
    select exists (select 1 from public.mail_accounts ma where ma.tenant_id = t and public.can_read_mailbox(ma.id));
$$;

-- ── Policies ────────────────────────────────────────────────────────────────
drop policy if exists mail_accounts_member on public.mail_accounts;
drop policy if exists mail_accounts_read on public.mail_accounts;
drop policy if exists mail_accounts_insert on public.mail_accounts;
drop policy if exists mail_accounts_update on public.mail_accounts;
drop policy if exists mail_accounts_delete on public.mail_accounts;
create policy mail_accounts_read on public.mail_accounts for select
    using (public.can_read_mailbox(id) or (public.is_member_strict(tenant_id) and public.is_tenant_admin(tenant_id)));
create policy mail_accounts_insert on public.mail_accounts for insert
    with check (public.is_member_strict(tenant_id) and user_id = auth.uid());
create policy mail_accounts_update on public.mail_accounts for update
    using (user_id = auth.uid() and public.is_member_strict(tenant_id)) with check (user_id = auth.uid());
create policy mail_accounts_delete on public.mail_accounts for delete
    using (public.is_member_strict(tenant_id) and (user_id = auth.uid() or public.is_tenant_admin(tenant_id)));

drop policy if exists email_messages_member on public.email_messages;
drop policy if exists email_messages_private on public.email_messages;
create policy email_messages_private on public.email_messages for all
    using (public.can_read_mailbox(mail_account_id)) with check (public.can_read_mailbox(mail_account_id));

drop policy if exists email_attachments_member on public.email_attachments;
drop policy if exists email_attachments_private on public.email_attachments;
create policy email_attachments_private on public.email_attachments for all
    using (public.can_read_email(email_id)) with check (public.can_read_email(email_id));

-- Review items from email are private; items without an email (none today) stay workspace-wide.
drop policy if exists inbox_items_member on public.inbox_items;
drop policy if exists inbox_items_private on public.inbox_items;
create policy inbox_items_private on public.inbox_items for all
    using (case when email_id is null then public.is_member(tenant_id) else public.can_read_email(email_id) end)
    with check (case when email_id is null then public.is_member(tenant_id) else public.can_read_email(email_id) end);

-- Feedback about an email or a review item follows that email's privacy; other AI feedback stays workspace-wide.
drop policy if exists ai_feedback_member on public.ai_feedback;
drop policy if exists ai_feedback_private on public.ai_feedback;
create policy ai_feedback_private on public.ai_feedback for all
    using (public.is_member(tenant_id)
           and (email_id is null or public.can_read_email(email_id))
           and (inbox_item_id is null or exists (select 1 from public.inbox_items i where i.id = inbox_item_id)))
    with check (public.is_member(tenant_id)
           and (email_id is null or public.can_read_email(email_id))
           and (inbox_item_id is null or exists (select 1 from public.inbox_items i where i.id = inbox_item_id)));

alter table public.mailbox_access enable row level security;
drop policy if exists mailbox_access_read on public.mailbox_access;
drop policy if exists mailbox_access_write on public.mailbox_access;
-- People with access can see who else has it; only the mailbox's owner changes the list.
create policy mailbox_access_read on public.mailbox_access for select using (public.can_read_mailbox(mail_account_id));
create policy mailbox_access_write on public.mailbox_access for all
    using (exists (select 1 from public.mail_accounts ma where ma.id = mail_account_id and ma.user_id = auth.uid()
                   and public.is_member_strict(ma.tenant_id)))
    with check (exists (select 1 from public.mail_accounts ma where ma.id = mail_account_id and ma.user_id = auth.uid()
                        and ma.tenant_id = mailbox_access.tenant_id and public.is_member_strict(ma.tenant_id))
                and exists (select 1 from public.memberships m where m.tenant_id = mailbox_access.tenant_id
                            and m.user_id = mailbox_access.user_id));
grant select, insert, update, delete on public.mailbox_access to authenticated;
