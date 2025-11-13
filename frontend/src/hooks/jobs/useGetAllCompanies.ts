import { useQuery } from "@tanstack/react-query";
import customRequest from "../../lib/axios";
import type { AllCompaniesResponse } from "../../types/companies";

export default function useGetAllCompanies() {
  const getAllCompanies = async () => {
    try {
      const response = await customRequest.get<AllCompaniesResponse>("/jobs/all-companies");

      if (response.status !== 200) {
        throw new Error(`Error: ${response.status} ${response.statusText}`);
      }

      return response.data;
    } catch (err) {
      console.error(err);
      throw new Error("Server Error");
    }
  };

  const { data: allCompanies, isFetching: isFetchingAllCompanies } = useQuery({
    queryKey: ["all-companies"],
    queryFn: getAllCompanies,
    refetchOnMount: true,
    refetchOnWindowFocus: false,
  });

  return {
    allCompanies,
    isFetchingAllCompanies,
  };
}
