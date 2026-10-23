// Which page to show for which URL.
import { Navigate, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { AuthPage } from "./pages/AuthPage";
import { MatchPage } from "./pages/MatchPage";
import { MatchesPage } from "./pages/MatchesPage";
import { UploadPage } from "./pages/UploadPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<AuthPage mode="login" />} />
      <Route path="/register" element={<AuthPage mode="register" />} />
      {/* Everything inside <Layout> requires login and shares the header. */}
      <Route element={<Layout />}>
        <Route path="/" element={<MatchesPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/matches/:id" element={<MatchPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
