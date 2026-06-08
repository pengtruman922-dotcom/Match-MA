import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { isLoggedIn } from '../lib/auth';

export default function ProtectedRoute() {
  const location = useLocation();
  if (!isLoggedIn()) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return <Outlet />;
}
