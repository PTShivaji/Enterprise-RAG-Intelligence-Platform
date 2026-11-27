import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Compass } from "lucide-react";
import { BrandMark } from "./components/layout/Brand";
import { EmptyState, Spinner } from "./components/ui";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { AppLayout } from "./layouts/AppLayout";
import LoginPage from "./pages/Login";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const Chat = lazy(() => import("./pages/Chat"));
const KnowledgeBase = lazy(() => import("./pages/KnowledgeBase"));
const Documents = lazy(() => import("./pages/Documents"));
const Search = lazy(() => import("./pages/Search"));
const Analytics = lazy(() => import("./pages/Analytics"));
const Settings = lazy(() => import("./pages/Settings"));

function FullScreenLoader() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4">
      <BrandMark className="size-9 animate-pulse" />
      <span className="sr-only">Loading</span>
    </div>
  );
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, initializing } = useAuth();
  const location = useLocation();
  if (initializing) return <FullScreenLoader />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return <>{children}</>;
}

function NotFound() {
  return (
    <EmptyState
      icon={Compass}
      title="Page not found"
      description="The page you are looking for does not exist."
      action={<Link to="/" className="text-sm font-medium text-violet-300 hover:underline">Back to overview</Link>}
    />
  );
}

export default function App() {
  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            element={
              <RequireAuth>
                <AppLayout />
              </RequireAuth>
            }
          >
            {[
              ["/", <Dashboard />],
              ["/chat", <Chat />],
              ["/knowledge", <KnowledgeBase />],
              ["/documents", <Documents />],
              ["/search", <Search />],
              ["/analytics", <Analytics />],
              ["/settings", <Settings />],
            ].map(([path, el]) => (
              <Route key={path as string} path={path as string} element={<Suspense fallback={<Spinner />}>{el}</Suspense>} />
            ))}
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
