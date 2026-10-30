"use client";

import { useEffect } from "react";
import { t } from "@/lib/api";
import { useData } from "@/lib/hooks";
import { useSession } from "@/lib/session";
import type { Member } from "@/lib/types";
import { Field, Select } from "./ui";

export function useTeam() {
  const { tenant } = useSession();
  return useData<Member[]>(t(tenant.id, "/team"));
}

/** "Uploaded by" picker; starts on you. Team members are managed in Settings → Users. */
export function UploadedBy({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const team = useTeam();
  useEffect(() => {
    if (!value && team.data) onChange(team.data.find((m) => m.is_me)?.id ?? team.data[0]?.id ?? "");
  }, [team.data]);   // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <Field label="Uploaded by" hint="Add people in Settings → Users">
      <Select value={value} onChange={onChange}
              options={(team.data ?? []).map((m) => [m.id, m.full_name + (m.is_me ? " (you)" : "")])} />
    </Field>
  );
}
