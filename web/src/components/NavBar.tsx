import { NavLink } from 'react-router-dom';
import { Sun, TrendingUp, Target, Clock, FlaskConical, Settings } from 'lucide-react';

const links = [
  { to: '/', icon: Sun, label: 'Today' },
  { to: '/training', icon: TrendingUp, label: 'Training' },
  { to: '/goal', icon: Target, label: 'Goal' },
  { to: '/history', icon: Clock, label: 'Activities' },
  { to: '/science', icon: FlaskConical, label: 'Science' },
  { to: '/settings', icon: Settings, label: 'Settings' },
];

export default function NavBar() {
  return (
    <>
      {/* Desktop sidebar */}
      <nav className="fixed inset-y-0 left-0 z-50 hidden w-64 border-r border-border bg-panel lg:block">
        <div className="flex h-16 items-center gap-3 px-6">
          <div className="h-8 w-8 rounded-lg bg-accent-green/20 flex items-center justify-center">
            <TrendingUp className="h-5 w-5 text-accent-green" />
          </div>
          <span className="text-lg font-semibold text-text-primary">TrailDash</span>
        </div>
        <div className="mt-4 space-y-1 px-3">
          {links.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-accent-green/10 text-accent-green'
                    : 'text-text-secondary hover:bg-panel-light hover:text-text-primary'
                }`
              }
            >
              <Icon className="h-5 w-5" />
              {label}
            </NavLink>
          ))}
        </div>
      </nav>

      {/* Mobile bottom nav */}
      <nav className="fixed inset-x-0 bottom-0 z-50 border-t border-border bg-panel/95 backdrop-blur-sm lg:hidden">
        <div className="flex h-16 items-center justify-around">
          {links.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              className={({ isActive }) =>
                `flex flex-col items-center gap-1 px-3 py-1 text-xs font-medium transition-colors ${
                  isActive ? 'text-accent-green' : 'text-text-muted'
                }`
              }
            >
              <Icon className="h-5 w-5" />
              {label}
            </NavLink>
          ))}
        </div>
      </nav>
    </>
  );
}
