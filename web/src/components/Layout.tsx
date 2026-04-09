import { Outlet } from 'react-router-dom';
import { SidebarProvider, SidebarTrigger } from '@/components/ui/sidebar';
import AppSidebar from '@/components/AppSidebar';

export default function Layout() {
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
    </SidebarProvider>
  );
}
