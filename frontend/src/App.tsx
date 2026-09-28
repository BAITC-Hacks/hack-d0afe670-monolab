import { Route, Routes } from "react-router-dom";
import CitizenApp from "./pages/CitizenApp";
import SpecialistPage from "./pages/SpecialistPage";
import TrackPage from "./pages/TrackPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<CitizenApp />} />
      <Route path="/track/:reg" element={<TrackPage />} />
      <Route path="/specialist" element={<SpecialistPage />} />
      <Route path="/admin" element={<SpecialistPage />} />
    </Routes>
  );
}
