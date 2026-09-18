import { Navigate, Route, Routes } from "react-router-dom";
import { StudioShell, WORKSPACES } from "./components/StudioShell";
import { ResearchPage } from "./pages/ResearchPage";
import { FactorsPage } from "./pages/FactorsPage";
import { BacktestPage } from "./pages/BacktestPage";
import { StrategiesPage } from "./pages/StrategiesPage";
import { RunsPage } from "./pages/RunsPage";

/** One route tree per market workspace: "/research" ... for A-shares, "/us/research" ... for US. */
export function App() {
  return (
    <Routes>
      {WORKSPACES.map((w) => (
        <Route key={w.region} path={w.base || "/"} element={<StudioShell key={w.region} region={w.region} />}>
          <Route index element={<Navigate to={`${w.base}/research`} replace />} />
          <Route path="research" element={<ResearchPage />} />
          <Route path="factors" element={<FactorsPage />} />
          <Route path="backtest" element={<BacktestPage />} />
          <Route path="strategies" element={<StrategiesPage />} />
          <Route path="runs" element={<RunsPage />} />
          <Route path="*" element={<Navigate to={`${w.base}/research`} replace />} />
        </Route>
      ))}
    </Routes>
  );
}
