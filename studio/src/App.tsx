import { Navigate, Route, Routes } from "react-router-dom";
import { StudioShell } from "./components/StudioShell";
import { ResearchPage } from "./pages/ResearchPage";
import { FactorsPage } from "./pages/FactorsPage";
import { BacktestPage } from "./pages/BacktestPage";
import { RunsPage } from "./pages/RunsPage";

export function App() {
  return (
    <Routes>
      <Route element={<StudioShell />}>
        <Route index element={<Navigate to="/research" replace />} />
        <Route path="/research" element={<ResearchPage />} />
        <Route path="/factors" element={<FactorsPage />} />
        <Route path="/backtest" element={<BacktestPage />} />
        <Route path="/runs" element={<RunsPage />} />
        <Route path="*" element={<Navigate to="/research" replace />} />
      </Route>
    </Routes>
  );
}
