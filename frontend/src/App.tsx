import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import ProtectedRoute from './components/ProtectedRoute';
import Home from './pages/Home';
import Targets from './pages/Targets';
import TargetDetail from './pages/TargetDetail';
import Buyers from './pages/Buyers';
import BuyerDetail from './pages/BuyerDetail';
import Updates from './pages/Updates';
import Recommend from './pages/Recommend';
import Dashboard from './pages/Dashboard';
import Settings from './pages/Settings';
import Login from './pages/Login';
import SearchResults from './pages/SearchResults';
import DebugCenter from './pages/DebugCenter';
import DebugEntityPage from './pages/DebugEntity';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="login" element={<Login />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="targets" element={<Targets />} />
            <Route path="targets/new" element={<Targets />} />
            <Route path="targets/:id" element={<TargetDetail />} />
            <Route path="buyers" element={<Buyers />} />
            <Route path="buyers/:id" element={<BuyerDetail />} />
            <Route path="recommendations" element={<Recommend />} />
            <Route path="search" element={<SearchResults />} />
            <Route path="debug" element={<DebugCenter />} />
            <Route path="debug/entities/:entityType/:entityId" element={<DebugEntityPage />} />
            <Route path="updates" element={<Updates />} />
            <Route path="updates/:id" element={<Updates />} />
            <Route path="dashboard" element={<Dashboard />} />
            <Route path="settings" element={<Settings />} />
            <Route path="recommend" element={<Navigate to="/recommendations" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

export default App;
