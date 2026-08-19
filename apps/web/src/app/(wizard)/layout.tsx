"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearSession, getStoredProfileId, getToken } from "@/lib/api";

const STEPS = [
  { href: "/train", label: "1. Train" },
  { href: "/looks", label: "2. Looks" },
  { href: "/create", label: "3. Create" },
];

export default function WizardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  // `null` = not yet checked. Must start identical on server and client — localStorage
  // doesn't exist during SSR, so reading it in a lazy initializer (as this used to do)
  // makes the client's first hydration render diverge from the server-rendered HTML,
  // causing a hydration mismatch. Deferring the real check to this effect (client-only,
  // post-hydration) is required here, not just a style preference.
  const [authorized, setAuthorized] = useState<boolean | null>(null);

  useEffect(() => {
    const ok = Boolean(getToken()) && Boolean(getStoredProfileId());
    // eslint-disable-next-line react-hooks/set-state-in-effect -- see comment above
    setAuthorized(ok);
    if (!ok) router.replace("/");
  }, [router]);

  if (authorized !== true) return null;

  return (
    <div className="min-h-screen">
      <header className="border-b border-neutral-200">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-4">
          <nav className="flex gap-6">
            {STEPS.map((step) => (
              <Link
                key={step.href}
                href={step.href}
                className={
                  pathname === step.href
                    ? "font-semibold text-neutral-900"
                    : "text-neutral-500 hover:text-neutral-700"
                }
              >
                {step.label}
              </Link>
            ))}
          </nav>
          <button
            onClick={() => {
              clearSession();
              router.push("/");
            }}
            className="text-sm text-neutral-400 hover:text-neutral-600"
          >
            Log out
          </button>
        </div>
      </header>
      <div className="mx-auto max-w-3xl px-6 py-8">{children}</div>
    </div>
  );
}
