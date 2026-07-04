import { redirect } from "next/navigation";

export default function FirmRedirectPage({ params }: { params: { id: string } }) {
  redirect(`/emailtag-firms?firm=${encodeURIComponent(params.id)}`);
}
