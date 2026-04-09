import { NavLink, useLocation } from 'react-router-dom';
import { Sun, Moon, Monitor, TrendingUp, Target, Clock, FlaskConical, Settings } from 'lucide-react';
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
} from '@/components/ui/sidebar';
import { useTheme } from '@/hooks/useTheme';

const navItems = [
  { to: '/', icon: Sun, label: 'Today' },
  { to: '/training', icon: TrendingUp, label: 'Training' },
  { to: '/goal', icon: Target, label: 'Goal' },
  { to: '/history', icon: Clock, label: 'Activities' },
  { to: '/science', icon: FlaskConical, label: 'Science' },
  { to: '/settings', icon: Settings, label: 'Settings' },
];

const THEME_CYCLE = ['dark', 'light', 'system'] as const;
const THEME_ICON = { dark: Moon, light: Sun, system: Monitor } as const;
const THEME_LABEL = { dark: 'Dark', light: 'Light', system: 'System' } as const;

export default function AppSidebar() {
  const location = useLocation();
  const { theme, setTheme } = useTheme();

  const cycleTheme = () => {
    const idx = THEME_CYCLE.indexOf(theme as typeof THEME_CYCLE[number]);
    const next = THEME_CYCLE[(idx + 1) % THEME_CYCLE.length];
    setTheme(next);
  };

  const ThemeIcon = THEME_ICON[theme as keyof typeof THEME_ICON] ?? Monitor;

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
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton onClick={cycleTheme} tooltip={`Theme: ${THEME_LABEL[theme as keyof typeof THEME_LABEL]}`}>
              <ThemeIcon />
              <span>{THEME_LABEL[theme as keyof typeof THEME_LABEL]}</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
