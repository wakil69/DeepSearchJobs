import { useMemo, useState } from "react";
import { useLocation } from "react-router-dom";
import type { ContractType, JobInfo } from "../../../types/jobs";
import useSetStatus from "../../../hooks/jobs/useSetStatus";
import SkillsModal from "./modals/SkillsModal";
import EmailsModal from "./modals/EmailsModal";
import { useTranslation } from "react-i18next";

export default function TableJobsRow({ job }: { job: JobInfo }) {
  const { t } = useTranslation();

  const [showSkills, setShowSkills] = useState(false);
  const [showEmails, setShowEmails] = useState(false);

  const location = useLocation();

  const currentPath = location.pathname;

  const showApplyActions = currentPath === "/jobs";
  const showAppliedActions = currentPath === "/applied-jobs";
  const showNotInterestedActions = currentPath === "/not-interested-jobs";

  const contractTypeLabels = useMemo<Record<ContractType, string>>(
    () => ({
      full_time: t("contractTypes.fullTime"),
      part_time: t("contractTypes.partTime"),
      internship: t("contractTypes.internship"),
      freelance: t("contractTypes.freelance"),
      short_term: t("contractTypes.shortTerm"),
      apprenticeship: t("contractTypes.apprenticeship"),
      graduate_program: t("contractTypes.graduateProgram"),
      remote: t("contractTypes.remote"),
    }),
    [t]
  );

  const { mutateJobStatus } = useSetStatus();

  const label =
    job.contractType && contractTypeLabels[job.contractType as ContractType]
      ? contractTypeLabels[job.contractType as ContractType]
      : t("contractTypes.fullTime");

  return (
    <>
      <tr className="border-b hover:bg-yellow-50 transition">
        <td className="px-4 py-3 font-medium text-blue-dark">{job.jobTitle}</td>
        <td className="px-4 py-3">{job.company}</td>
        <td className="px-4 py-3">{job.locationCountry}</td>
        <td className="px-4 py-3">{job.locationRegion}</td>
        <td className="px-4 py-3">{label}</td>
        <td className="px-4 py-3">{job.salary || "—"}</td>
        <td className="px-4 py-3">{job.dateFetched}</td>

        <td className="px-4 py-3 flex flex-wrap justify-center gap-2">
          {/* Apply */}
          <button
            onClick={() => window.open(job.jobUrl, "_blank")}
            className="cursor-pointer px-2 py-1 text-sm bg-green-600 text-white rounded-md hover:bg-green-700"
          >
            {t("apply")}
          </button>

          {/* Skills modal */}
          <button
            onClick={() => setShowSkills(true)}
            className="cursor-pointer px-2 py-1 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700"
          >
            {t("skills")}
          </button>

          {/* Emails modal */}
          <button
            onClick={() => setShowEmails(true)}
            className="cursor-pointer px-2 py-1 text-sm bg-purple-600 text-white rounded-md hover:bg-purple-700"
          >
            {t("emails")}
          </button>

          {/* Dynamic actions based on route */}
          {showApplyActions && (
            <>
              <button
                onClick={() =>
                  mutateJobStatus({ jobId: job.id, status: "applied" })
                }
                className="cursor-pointer px-2 py-1 text-sm bg-yellow-400 text-blue-dark rounded-md hover:bg-yellow-300"
              >
                {t("setApplied")}
              </button>

              <button
                onClick={() =>
                  mutateJobStatus({ jobId: job.id, status: "not_interested" })
                }
                className="cursor-pointer px-2 py-1 text-sm bg-red-500 text-white rounded-md hover:bg-red-600"
              >
                {t("setNotInterested")}
              </button>
            </>
          )}

          {showAppliedActions && (
            <button
              onClick={() =>
                mutateJobStatus({ jobId: job.id, status: "not_interested" })
              }
              className="cursor-pointer px-2 py-1 text-sm bg-red-500 text-white rounded-md hover:bg-red-600"
            >
              {t("setNotInterested")}
            </button>
          )}

          {showNotInterestedActions && (
            <button
              onClick={() =>
                mutateJobStatus({ jobId: job.id, status: "applied" })
              }
              className="cursor-pointer px-2 py-1 text-sm bg-yellow-400 text-blue-dark rounded-md hover:bg-yellow-300"
            >
              {t("setApplied")}
            </button>
          )}
        </td>
      </tr>

      {/* Skills Modal */}
      {showSkills && (
        <SkillsModal
          skills={job.skillsRequired}
          setShowSkills={setShowSkills}
        />
      )}

      {/* Emails Modal */}
      {showEmails && (
        <EmailsModal emails={job.emails} setShowEmails={setShowEmails} />
      )}
    </>
  );
}
