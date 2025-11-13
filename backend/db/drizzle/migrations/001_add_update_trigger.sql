-- Function to auto-update "update_date"
CREATE OR REPLACE FUNCTION update_update_date_column()
RETURNS TRIGGER AS $$
BEGIN
  NEW.update_date = NOW();
  RETURN NEW;
END;
$$ LANGUAGE 'plpgsql';

-- Triggers for all tables
CREATE TRIGGER update_companies_update_date
BEFORE UPDATE ON companies
FOR EACH ROW
EXECUTE FUNCTION update_update_date_column();

CREATE TRIGGER update_all_jobs_update_date
BEFORE UPDATE ON all_jobs
FOR EACH ROW
EXECUTE FUNCTION update_update_date_column();

CREATE TRIGGER update_jobs_proposals_update_date
BEFORE UPDATE ON jobs_proposals
FOR EACH ROW
EXECUTE FUNCTION update_update_date_column();
