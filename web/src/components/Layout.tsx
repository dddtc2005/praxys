import { Outlet } from 'react-router-dom';
import NavBar from '@/components/NavBar';

export default function Layout() {
  return (
    <div className="min-h-screen bg-background">
      <NavBar />
      <main className="pb-20 lg:pb-0 lg:pl-64">
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
