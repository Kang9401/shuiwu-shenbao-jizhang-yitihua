from app.models.accounting import (
    CertificationLedger,
    InvoiceLedger,
    OrganizationMapping,
    PersonnelMasterArtifact,
    PersonnelMasterImportBatch,
    ReconciliationImportBatch,
    ReconciliationImportRow,
    VoucherDraft,
)
from app.models.core import Artifact, Company, Job, Period, UploadedFile
from app.models.tax import TaxMonthlyArtifact, VerificationRound, VerificationSession


COMPANY_SCOPED_MODELS = (
    Period,
    UploadedFile,
    Job,
    Artifact,
    InvoiceLedger,
    CertificationLedger,
    VoucherDraft,
    PersonnelMasterArtifact,
    PersonnelMasterImportBatch,
    ReconciliationImportBatch,
    ReconciliationImportRow,
    OrganizationMapping,
    VerificationSession,
    VerificationRound,
    TaxMonthlyArtifact,
)

__all__ = [model.__name__ for model in (*COMPANY_SCOPED_MODELS, Company)]
