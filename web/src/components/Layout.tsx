import { Outlet } from 'react-router-dom';
import { SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar';
import AppSidebar from '@/components/AppSidebar';
import { useAuth } from '@/hooks/useAuth';
import { Eye } from 'lucide-react';

export default function Layout() {
  const { isDemo } = useAuth();

  return (
    <SidebarProvider>
      <AppSidebar />
      <main className="flex-1 min-h-screen">
        <header className="sticky top-0 z-40 flex h-12 items-center gap-2 border-b border-border bg-background/80 backdrop-blur-sm px-4 lg:hidden">
          <SidebarTrigger />
        </header>
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </div>
      </main>

      {/* Floating demo banner — always visible, anchored to bottom */}
      {isDemo && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 animate-in fade-in slide-in-from-bottom-4 duration-500">
          <div className="flex items-center gap-2 rounded-full border border-amber-500/30 bg-amber-950/80 dark:bg-amber-950/90 backdrop-blur-md px-4 py-2 shadow-lg shadow-amber-900/20">
            <Eye className="h-3.5 w-3.5 text-amber-400 shrink-0" />
            <span className="text-xs font-medium text-amber-200 whitespace-nowrap">
              Live demo — real training data, read-only
            </span>
            <span className="h-1.5 w-1.5 rounded-full bg-amber-400 animate-pulse shrink-0" />
          </div>
        </div>
      )}
    </SidebarProvider>
  );
}
