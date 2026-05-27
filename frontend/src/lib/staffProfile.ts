import { api } from "./api";

export interface StaffProfilePayload {
  surname_jp?: string;
  given_name_jp?: string;
  surname_kana?: string;
  given_name_kana?: string;
  surname_en?: string;
  given_name_en?: string;
  phone?: string | null;
}

export async function patchMyProfile(payload: StaffProfilePayload): Promise<void> {
  await api.patch("/staff/me/profile", payload);
}
