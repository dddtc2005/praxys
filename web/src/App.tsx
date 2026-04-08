import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { SettingsProvider } from './contexts/SettingsContext';
import { ScienceProvider } from './contexts/ScienceContext';
import Layout from './components/Layout';
import Today from './pages/Today';
import Training from './pages/Training';
import Goal from './pages/Goal';
import History from './pages/History';
import Settings from './pages/Settings';

export default function App() {
  return (
    <SettingsProvider>
      <ScienceProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Today />} />
            <Route path="training" element={<Training />} />
            <Route path="goal" element={<Goal />} />
            <Route path="history" element={<History />} />
            <Route path="settings" element={<Settings />} />
          </Route>
        </Routes>
      </BrowserRouter>
      </ScienceProvider>
    </SettingsProvider>
  );
}
