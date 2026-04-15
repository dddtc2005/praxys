import { NavLink, useLocation } from 'react-router-dom';
import { Sun, Moon, Monitor, TrendingUp, Target, Clock, FlaskConical, Settings, LogOut, ListChecks } from 'lucide-react';
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


const THEME_CYCLE = ['dark', 'light', 'system'] as const;
const THEME_ICON = { dark: Moon, light: Sun, system: Monitor } as const;
const THEME_LABEL = { dark: 'Dark', light: 'Light', system: 'System' } as const;

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
  const { logout, email } = useAuth();
  const { config } = useSettings();
  const setup = useSetupStatus();
  const displayName = config?.display_name || null;

  // Dynamic nav: show Setup instead of Today when onboarding is incomplete
  const homeItem = setup.allDone || setup.loading
    ? { to: '/', icon: Sun, label: 'Today' }
    : { to: '/', icon: ListChecks, label: `Setup (${setup.completed}/${setup.total})` };

  const navItems = [
    homeItem,
    { to: '/training', icon: TrendingUp, label: 'Training' },
    { to: '/goal', icon: Target, label: 'Goal' },
    { to: '/history', icon: Clock, label: 'Activities' },
    { to: '/science', icon: FlaskConical, label: 'Science' },
    { to: '/settings', icon: Settings, label: 'Settings' },
  ];

  const cycleTheme = () => {
    const idx = THEME_CYCLE.indexOf(theme);
    const next = THEME_CYCLE[(idx + 1) % THEME_CYCLE.length];
    setTheme(next);
  };

  const ThemeIcon = THEME_ICON[theme] ?? Monitor;

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-3 px-2 py-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/20">
            <TrendingUp className="h-5 w-5 text-primary" />
          </div>
          <span className="text-lg font-semibold text-foreground group-data-[collapsible=icon]:hidden">
            Trainsight
          </span>
        </div>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              {navItems.map(({ to, icon: Icon, label }) => {
                const isActive =
                  to === '/'
                    ? location.pathname === '/'
                    : location.pathname.startsWith(to);
                return (
                  <SidebarMenuItem key={to}>
                    <SidebarMenuButton
                      render={<NavLink to={to} />}
                      isActive={isActive}
                      tooltip={label}
                    >
                      <Icon />
                      <span>{label}</span>
                    </SidebarMenuButton>
                  </SidebarMenuItem>
                );
              })}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
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
            <SidebarMenuButton onClick={cycleTheme} tooltip={`Theme: ${THEME_LABEL[theme]}`}>
              <ThemeIcon />
              <span>{THEME_LABEL[theme]}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem>
              <SidebarMenuButton onClick={logout} tooltip="Log out">
                <LogOut />
                <span>Log out</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
