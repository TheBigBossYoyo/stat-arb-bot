import { Route, Routes } from "react-router-dom";
import Layout from "./components/layout/Layout";
import CommandCenterPage from "./pages/CommandCenterPage";
import Dashboard from "./pages/Dashboard";
import Portfolio from "./pages/Portfolio";
import Risk from "./pages/Risk";
import Execution from "./pages/Execution";
import Strategies from "./pages/Strategies";
import Pairs from "./pages/Pairs";
import Backtests from "./pages/Backtests";
import BacktestDetail from "./pages/BacktestDetail";
import Brokers from "./pages/Brokers";
import Logs from "./pages/Logs";
import Settings from "./pages/Settings";
import ProductDecisionPage from "./pages/ProductDecisionPage";
import TradabilityMatrixPage from "./pages/TradabilityMatrixPage";
import BlockersPage from "./pages/BlockersPage";
import LiveReadinessPage from "./pages/LiveReadinessPage";
import ReadinessPage from "./pages/ReadinessPage";
import ConcentrationDiagnosticsPage from "./pages/ConcentrationDiagnosticsPage";
import DeflatedSharpePage from "./pages/DeflatedSharpePage";
import CrisisLabPage from "./pages/CrisisLabPage";
import SurvivorshipPage from "./pages/SurvivorshipPage";
import LongOnlyPaperSetupPage from "./pages/LongOnlyPaperSetupPage";
import Trading212OrderPreviewPage from "./pages/Trading212OrderPreviewPage";
import Trading212SetupPage from "./pages/Trading212SetupPage";
import SupervisedPaperMonitorPage from "./pages/SupervisedPaperMonitorPage";
import SupervisedPaperPage from "./pages/SupervisedPaperPage";
import OperatorPaperModePage from "./pages/OperatorPaperModePage";
import ReportsLibraryPage from "./pages/ReportsLibraryPage";
import SafetyCenterPage from "./pages/SafetyCenterPage";

export default function App() {
  return (
    <Layout>
      <Routes>
        {/* Command Center */}
        <Route path="/" element={<CommandCenterPage />} />
        <Route path="/product-decision" element={<ProductDecisionPage />} />
        <Route path="/tradability" element={<TradabilityMatrixPage />} />

        {/* Long-only T212 */}
        <Route path="/readiness" element={<ReadinessPage />} />
        <Route path="/concentration" element={<ConcentrationDiagnosticsPage />} />
        <Route path="/survivorship" element={<SurvivorshipPage />} />
        <Route path="/crisis-lab" element={<CrisisLabPage />} />
        <Route path="/order-preview" element={<Trading212OrderPreviewPage />} />

        {/* Supervised Paper */}
        <Route path="/supervised-paper" element={<SupervisedPaperPage />} />
        <Route path="/operator" element={<OperatorPaperModePage />} />
        <Route path="/paper-monitor" element={<SupervisedPaperMonitorPage />} />
        <Route path="/paper-setup" element={<LongOnlyPaperSetupPage />} />

        {/* Broker */}
        <Route path="/t212-setup" element={<Trading212SetupPage />} />
        <Route path="/brokers" element={<Brokers />} />

        {/* Risk & Safety */}
        <Route path="/live-readiness" element={<LiveReadinessPage />} />
        <Route path="/safety" element={<SafetyCenterPage />} />
        <Route path="/blockers" element={<BlockersPage />} />

        {/* Research */}
        <Route path="/reports" element={<ReportsLibraryPage />} />
        <Route path="/backtests" element={<Backtests />} />
        <Route path="/backtests/:id" element={<BacktestDetail />} />
        <Route path="/deflated-sharpe" element={<DeflatedSharpePage />} />

        {/* System / markets */}
        <Route path="/legacy" element={<Dashboard />} />
        <Route path="/portfolio" element={<Portfolio />} />
        <Route path="/risk" element={<Risk />} />
        <Route path="/execution" element={<Execution />} />
        <Route path="/strategies" element={<Strategies />} />
        <Route path="/pairs" element={<Pairs />} />
        <Route path="/logs" element={<Logs />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </Layout>
  );
}
