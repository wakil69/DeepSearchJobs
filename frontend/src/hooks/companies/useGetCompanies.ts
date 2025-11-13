import { useQuery } from "@tanstack/react-query";
import customRequest from "../../lib/axios";
import type { CompaniesResponse } from "../../types/companies";

export interface GetCompaniesParams {
  page?: number;
  pageSize?: number;
  search?: string;
  statusFilter?: string;
}

export default function useGetCompanies(params: GetCompaniesParams) {
  const getCompanies = async () => {
    try {
      const response = await customRequest.get<CompaniesResponse>("/companies/", {
        params,
      });

      if (response.status !== 200) {
        throw new Error(`Error: ${response.status} ${response.statusText}`);
      }

      return response.data;
    } catch (err) {
      console.error(err);
      throw new Error("Server Error");
    }
  };

  const { data: companiesResponse, isFetching: isFetchingCompanies, refetch: refetchCompanies } = useQuery({
    queryKey: ["companies", params],
    queryFn: getCompanies,
    refetchOnMount: true,
    refetchOnWindowFocus: false,
  });

  return {
    companiesResponse,
    isFetchingCompanies,
    refetchCompanies
  };
}
