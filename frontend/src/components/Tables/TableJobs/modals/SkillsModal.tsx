import type { Dispatch, SetStateAction } from "react";
import { useTranslation } from "react-i18next";

interface SkillsModalProps {
  skills?: string[];
  setShowSkills: Dispatch<SetStateAction<boolean>>;
}

export default function SkillsModal({
  skills,
  setShowSkills,
}: SkillsModalProps) {
  const { t } = useTranslation()
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-lg shadow-lg w-full max-w-md max-h-[80vh] flex flex-col">
        <div className="p-4 border-b">
          <h3 className="text-lg font-bold text-blue-dark">
            {t("skillsRequired")}
          </h3>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {skills && skills.length > 0 ? (
            <ul className="list-disc list-inside text-gray-700 space-y-1">
              {skills.map((skill, i) => (
                <li key={i}>{skill}</li>
              ))}
            </ul>
          ) : (
            <p className="text-gray-500 italic">{t("noSkillsListed")}</p>
          )}
        </div>

        <div className="p-4 border-t flex justify-end">
          <button
            onClick={() => setShowSkills(false)}
            className="bg-yellow-400 text-blue-dark px-4 py-1 rounded-md hover:bg-yellow-300"
          >
            {t("close")}
          </button>
        </div>
      </div>
    </div>
  );
}
