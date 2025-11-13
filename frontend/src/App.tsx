import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
} from "react-router-dom";
import Jobs from "./pages/Jobs";
import Companies from "./pages/Companies";
import AppliedJobs from "./pages/AppliedJobs";
import NotInterestedJobs from "./pages/NotInterestedJobs";
import Layout from "./layouts/Layout";

function App() {
  return (
    <Router>
      <Routes>
        {/* Default route */}
        <Route path="/" element={<Navigate to="/jobs" replace />} />

        <Route element={<Layout />}>
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/companies" element={<Companies />} />
          <Route path="/applied-jobs" element={<AppliedJobs />} />
          <Route path="/not-interested-jobs" element={<NotInterestedJobs />} />
        </Route>
      </Routes>
    </Router>
  );
}

export default App;
