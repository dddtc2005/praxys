import type { ComponentType, SVGProps } from 'react';
import { Activity, AlertTriangle, Megaphone, MessageSquarePlus, ShieldCheck, Users } from 'lucide-react';
import { Navigate, NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '@/hooks/useAuth';
import { Trans, useLingui } from '@lingui/react/macro';

type NavItem = {
  to: string;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  label: string;
};

export default function AdminLayout() {
  const { isAdmin } = useAuth();
  const { t } = useLingui();

  if (!isAdmin) {
    return <Navigate to="/today" replace />;
  }

  const navItems: NavItem[] = [
    { to: '/admin/ops', icon: Activity, label: t`Operations` },
    { to: '/admin/users', icon: Users, label: t`Users` },
    { to: '/admin/feedback', icon: MessageSquarePlus, label: t`Feedback` },
    { to: '/admin/incidents', icon: AlertTriangle, label: t`Incidents` },
    { to: '/admin/communications', icon: Megaphone, label: t`Communications` },
  ];

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div>
          <p className="inline-flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.18em] text-muted-foreground">
            <ShieldCheck className="h-3.5 w-3.5" />
            <Trans>Admin</Trans>
          </p>
          <h1 className="mt-1 text-xl font-semibold tracking-tight text-foreground">
            <Trans>Admin console</Trans>
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            <Trans>Management routes for access, communications, and service status.</Trans>
          </p>
        </div>

        <nav aria-label={t`Admin sections`}>
          <ul className="flex flex-wrap gap-2">
            {navItems.map(({ to, icon: Icon, label }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  className={({ isActive }) =>
                    [
                      'inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
                      isActive
                        ? 'border-border bg-muted text-foreground'
                        : 'border-border/70 text-muted-foreground hover:border-border hover:text-foreground',
                    ].join(' ')
                  }
                >
                  <Icon className="h-4 w-4" />
                  <span>{label}</span>
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </div>

      <Outlet />
    </div>
  );
}
