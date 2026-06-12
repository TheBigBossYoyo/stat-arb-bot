import { Route, Routes } from "react-router-dom";
import Layout from "./components/layout/Layout";
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

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/portfolio" element={<Portfolio />} />
        <Route path="/risk" element={<Risk />} />
        <Route path="/execution" element={<Execution />} />
        <Route path="/strategies" element={<Strategies />} />
        <Route path="/pairs" element={<Pairs />} />
        <Route path="/backtests" element={<Backtests />} />
        <Route path="/backtests/:id" element={<BacktestDetail />} />
        <Route path="/brokers" element={<Brokers />} />
        <Route path="/logs" element={<Logs />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </Layout>
  );
}
