import { NavLink, useLocation } from 'react-router-dom';
import type { ComponentType, SVGProps } from 'react';
import { Sun, Moon, Monitor, TrendingUp, Target, Clock, FlaskConical, Settings, LogOut, ListChecks, ShieldCheck } from 'lucide-react';
import { PraxysFlag } from '@/components/PraxysFlag';
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarSeparator,
} from '@/components/ui/sidebar';
import { useTheme } from '@/hooks/useTheme';
import { useAuth } from '@/hooks/useAuth';
import { useSettings } from '@/contexts/SettingsContext';
import { useSetupStatus } from '@/hooks/useSetupStatus';
import { useLingui } from '@lingui/react/macro';
import { msg } from '@lingui/core/macro';
import type { MessageDescriptor } from '@lingui/core';


const THEME_CYCLE = ['light', 'dark', 'system'] as const;
const THEME_ICON = { dark: Moon, light: Sun, system: Monitor } as const;
const THEME_LABEL: Record<typeof THEME_CYCLE[number], MessageDescriptor> = {
  dark: msg`Dark`,
  light: msg`Light`,
  system: msg`System`,
};

// Praxys wordmark — "Pra" + green X + "ys" per the brand guide. Plain
// text was wrong; this puts the brand identity in the chrome where it
// belongs.
function PraxysWordmark() {
  return (
    <span className="text-lg font-semibold tracking-tight text-foreground group-data-[collapsible=icon]:hidden">
      Pra<span className="text-primary">x</span>ys
    </span>
  );
}

type NavItem = { to: string; icon: ComponentType<SVGProps<SVGSVGElement>>; label: string };

// Single-row nav button with the new active-state treatment: 3px primary
// left edge + bolder weight, no background fill (per DESIGN.md sidebar
// rule). Overrides shadcn's default data-[active=true]:bg-sidebar-accent.
//
// The 3px indicator is anchored to SidebarMenuItem (which has `relative`
// and no overflow-hidden), not the inner button (which IS overflow-hidden
// per shadcn's sidebarMenuButtonVariants). Painting the pseudo-element
// on the button would clip the rounded-r corner.
function NavItemRow({ item, isActive, tooltip }: { item: NavItem; isActive: boolean; tooltip?: string }) {
  const { icon: Icon, label, to } = item;
  return (
    <SidebarMenuItem
      className={
        isActive
          ? 'before:absolute before:inset-y-1.5 before:left-0 before:w-[3px] before:bg-primary before:rounded-r-sm'
          : ''
      }
    >
      <SidebarMenuButton
        render={<NavLink to={to} />}
        isActive={isActive}
        tooltip={tooltip ?? label}
        className={isActive ? '!bg-transparent !text-foreground font-semibold' : ''}
      >
        <Icon />
        <span>{label}</span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}

function UserInitials({ name, email }: { name?: string; email: string | null }) {
  let initials = '?';
  if (name && name.trim()) {
    const parts = name.trim().split(/\s+/);
    initials = parts.length >= 2
      ? (parts[0][0] + parts[1][0]).toUpperCase()
      : name.slice(0, 2).toUpperCase();
  } else if (email) {
    initials = email.split('@')[0].slice(0, 2).toUpperCase();
  }
  return (
    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-primary/15 text-[11px] font-semibold tracking-wide text-primary ring-1 ring-primary/20">
      {initials}
    </div>
  );
}

export default function AppSidebar() {
  const location = useLocation();
  const { theme, setTheme } = useTheme();
  const { logout, email, isAdmin } = useAuth();
  const { config } = useSettings();
  const setup = useSetupStatus();
  const { t, i18n } = useLingui();
  const displayName = config?.display_name || null;

  // Active-cluster: daily-use training surfaces. Today, Training, Goal,
  // Activities. The home item stays "Today" regardless of setup state —
  // setup gets its own dedicated banner row above the active cluster.
  const activeItems: NavItem[] = [
    { to: '/today', icon: Sun, label: t`Today` },
    { to: '/training', icon: TrendingUp, label: t`Training` },
    { to: '/goal', icon: Target, label: t`Goal` },
    { to: '/history', icon: Clock, label: t`Activities` },
  ];
  // Reference: theory + methodology surfaces.
  const referenceItems: NavItem[] = [
    { to: '/science', icon: FlaskConical, label: t`Science` },
  ];
  // Configuration: the user adjusts the system here (rare, deliberate).
  const configItems: NavItem[] = [
    { to: '/settings', icon: Settings, label: t`Settings` },
    ...(isAdmin ? [{ to: '/admin', icon: ShieldCheck, label: t`Admin` }] : []),
  ];

  const isActive = (to: string) =>
    to === '/today' ? location.pathname === '/today' : location.pathname.startsWith(to);

  // Setup is shown as a dashed-border callout row above the active cluster
  // when onboarding is incomplete, instead of replacing the Today slot.
  // Routes to /setup (the dedicated wizard page) so the user lands
  // somewhere different from Today's row directly below — otherwise the
  // banner would just duplicate Today's link and never reflect "active"
  // when the user is on /today.
  const setupIncomplete = !setup.allDone && !setup.loading;
  const setupBanner = setupIncomplete ? (
    <SidebarMenuItem>
      <SidebarMenuButton
        render={<NavLink to="/setup" />}
        isActive={location.pathname.startsWith('/setup')}
        tooltip={`${t`Setup`} (${setup.completed}/${setup.total})`}
        className="border border-dashed border-primary/40 bg-primary/5 hover:bg-primary/10 data-[active=true]:bg-primary/10"
      >
        <ListChecks />
        <span>{`${t`Setup`} (${setup.completed}/${setup.total})`}</span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  ) : null;

  const cycleTheme = () => {
    const idx = THEME_CYCLE.indexOf(theme);
    const next = THEME_CYCLE[(idx + 1) % THEME_CYCLE.length];
    setTheme(next);
  };

  const ThemeIcon = THEME_ICON[theme] ?? Monitor;

  // Header / footer are identical across all three variants — extract once.
  const headerContent = (
    <SidebarHeader>
      <div className="flex items-center gap-2.5 px-2 py-2">
        <PraxysFlag className="h-8 w-8 shrink-0" />
        <PraxysWordmark />
      </div>
    </SidebarHeader>
  );

  const footerContent = (
    <SidebarFooter>
      {email && (
        <>
          <div className="flex items-center gap-2 px-2 py-1.5">
            <UserInitials name={displayName ?? undefined} email={email} />
            <div className="flex flex-col overflow-hidden group-data-[collapsible=icon]:hidden">
              {displayName ? (
                <>
                  <span className="truncate text-xs font-medium text-foreground">{displayName}</span>
                  <span className="truncate text-[10px] text-muted-foreground">{email}</span>
                </>
              ) : (
                <span className="truncate text-xs text-muted-foreground">{email}</span>
              )}
            </div>
          </div>
          <SidebarSeparator />
        </>
      )}
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton onClick={cycleTheme} tooltip={`${t`Theme`}: ${i18n._(THEME_LABEL[theme])}`}>
            <ThemeIcon />
            <span>{i18n._(THEME_LABEL[theme])}</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
        <SidebarMenuItem>
          <SidebarMenuButton onClick={logout} tooltip={t`Log out`}>
            <LogOut />
            <span>{t`Log out`}</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarFooter>
  );

  return (
    <Sidebar collapsible="icon">
      {headerContent}
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {setupBanner}
              {activeItems.map((item) => (
                <NavItemRow key={item.to} item={item} isActive={isActive(item.to)} />
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarSeparator />
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {referenceItems.map((item) => (
                <NavItemRow key={item.to} item={item} isActive={isActive(item.to)} />
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
        <SidebarSeparator />
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {configItems.map((item) => (
                <NavItemRow key={item.to} item={item} isActive={isActive(item.to)} />
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      {footerContent}
    </Sidebar>
  );
}
