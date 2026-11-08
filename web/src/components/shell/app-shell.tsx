"use client";

import {
  Activity,
  Bot,
  Boxes,
  BrainCircuit,
  CreditCard,
  FlaskConical,
  Menu,
  Orbit,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useState } from "react";
import { ConnectionIndicator } from "./connection-indicator";

const navigation = [
  { label: "Agent", href: "/", icon: Bot },
  { label: "Observatory", href: "/observatory", icon: Orbit },
  { label: "World", href: "/world", icon: FlaskConical },
  { label: "Generations", href: "/world/generations", icon: Boxes },
  { label: "Episodes", href: "/episodes", icon: Activity },
  { label: "Models", href: "/models", icon: BrainCircuit },
  { label: "Payments", href: "/payments", icon: CreditCard },
  { label: "System", href: "/system", icon: Activity },
];

function Logo() {
  return (
    <Link href="/" className="group flex items-center gap-3" aria-label="Crucible home">
      <span className="relative grid size-9 place-items-center overflow-hidden rounded-xl border border-emerald-300/20 bg-emerald-200/5">
        <span className="absolute inset-[7px] rotate-45 border border-emerald-300/60" />
        <span className="size-1.5 rounded-full bg-emerald-200 shadow-[0_0_14px_#a6ffcb]" />
      </span>
      <span>
        <span className="block text-sm font-semibold tracking-[0.18em] text-white uppercase">
          Crucible
        </span>
        <span className="block font-mono text-[0.55rem] tracking-[0.15em] text-slate-500 uppercase">
          Evidence before action
        </span>
      </span>
    </Link>
  );
}

function Navigation({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Primary" className="mt-9 space-y-1">
      {navigation.map(({ label, href, icon: Icon }) => {
        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={`group flex items-center gap-3 rounded-lg border px-3 py-2.5 text-sm transition-colors ${
              active
                ? "border-emerald-300/15 bg-emerald-300/[0.07] text-emerald-100"
                : "border-transparent text-slate-400 hover:border-white/8 hover:bg-white/[0.03] hover:text-slate-100"
            }`}
          >
            <Icon
              className={`size-4 ${active ? "text-emerald-300" : "text-slate-600 group-hover:text-slate-400"}`}
              aria-hidden="true"
            />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  const immersive = pathname === "/observatory";

  if (immersive) {
    return (
      <div className="min-h-screen">
        <a
          href="#main-content"
          className="fixed top-3 left-3 z-50 -translate-y-20 rounded-lg bg-emerald-200 px-4 py-2 text-sm font-semibold text-slate-950 focus:translate-y-0"
        >
          Skip to training world
        </a>
        <main id="main-content" className="min-h-screen">
          {children}
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <a
        href="#main-content"
        className="fixed top-3 left-3 z-50 -translate-y-20 rounded-lg bg-emerald-200 px-4 py-2 text-sm font-semibold text-slate-950 focus:translate-y-0"
      >
        Skip to content
      </a>

      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 border-r border-white/8 bg-[#07100f]/95 px-5 py-6 backdrop-blur-xl lg:block">
        <Logo />
        <Navigation />
        <div className="absolute inset-x-5 bottom-6 border-t border-white/8 pt-5">
          <ConnectionIndicator />
          <p className="mt-3 font-mono text-[0.6rem] leading-4 tracking-[0.08em] text-slate-600 uppercase">
            Shopping decisions are auditable. Purchases require confirmation.
          </p>
        </div>
      </aside>

      <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-white/8 bg-[#07100f]/90 px-4 backdrop-blur-xl lg:hidden">
        <Logo />
        <button
          type="button"
          className="grid size-10 place-items-center rounded-lg border border-white/10 text-slate-300"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          aria-controls="mobile-navigation"
          aria-label={open ? "Close navigation" : "Open navigation"}
        >
          {open ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
      </header>

      {open ? (
        <div
          id="mobile-navigation"
          className="fixed inset-x-0 top-16 z-20 border-b border-white/10 bg-[#07100f] px-4 pb-5 shadow-2xl lg:hidden"
        >
          <Navigation onNavigate={() => setOpen(false)} />
          <div className="mt-5 border-t border-white/8 pt-4">
            <ConnectionIndicator />
          </div>
        </div>
      ) : null}

      <main id="main-content" className="min-h-screen px-4 py-8 sm:px-6 lg:ml-64 lg:px-10 lg:py-10">
        <div className="mx-auto max-w-[1480px]">{children}</div>
      </main>
    </div>
  );
}
