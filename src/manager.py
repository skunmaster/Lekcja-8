from datetime import datetime, date
from typing import List

from src.models import (
    Apartment,
    Bill,
    Parameters,
    Tenant,
    ApartmentEvent,
    TenantBlacklistEntry,
    TenantSettlement,
    Transfer,
    ApartmentSettlement,
)


class Manager:
    def __init__(self, parameters: Parameters):
        self.parameters = parameters
        self.apartments = {}
        self.tenants = {}
        self.transfers = []
        self.bills = []
        self.tenants_blacklist = []
        self.apartment_events = []

        self.load_data()
        self.load_additional_data()

    def _validate_month(self, month: int):
        if month < 1 or month > 12:
            raise ValueError("Month must be between 1 and 12")

    def load_data(self):
        self.apartments = Apartment.from_json_file(
            self.parameters.apartments_json_path
        )
        self.tenants = Tenant.from_json_file(
            self.parameters.tenants_json_path
        )
        self.transfers = Transfer.from_json_file(
            self.parameters.transfers_json_path
        )
        self.bills = Bill.from_json_file(
            self.parameters.bills_json_path
        )
        self.tenants_blacklist = TenantBlacklistEntry.from_json_file(
            self.parameters.tenants_blacklist_json_path
        )

    def load_additional_data(self):
        self.apartment_events = ApartmentEvent.from_json_file(
            self.parameters.apartment_events_json_path
        )

    def generate_apartment_events_report(
        self,
        apartment_key: str,
        only_unsolved: bool = True
    ) -> List[ApartmentEvent]:
        if apartment_key not in self.apartments:
            raise ValueError("Apartment key does not exist")

        return [
            event
            for event in self.apartment_events
            if event.apartment == apartment_key
            and (
                not only_unsolved
                or not event.solved
            )
        ]

    def check_tenants_apartment_keys(self) -> bool:
        return all(
            tenant.apartment in self.apartments
            for tenant in self.tenants.values()
        )

    def get_apartment(self, apartment_key: str) -> Apartment | None:
        return self.apartments.get(apartment_key)

    def get_apartment_costs(
        self,
        apartment_key: str,
        year: int = None,
        month: int = None
    ) -> float | None:
        if month is not None:
            self._validate_month(month)

        if apartment_key not in self.apartments:
            return None

        total_cost = sum(
            bill.amount_pln
            for bill in self.bills
            if bill.apartment == apartment_key
            and (year is None or bill.settlement_year == year)
            and (month is None or bill.settlement_month == month)
        )

        return total_cost

    def get_settlement(
        self,
        apartment_key: str,
        year: int,
        month: int
    ) -> ApartmentSettlement | None:
        self._validate_month(month)

        if apartment_key not in self.apartments:
            return None

        if not self.has_any_bills(apartment_key, year, month):
            return None

        total_cost = self.get_apartment_costs(
            apartment_key,
            year,
            month
        )

        return ApartmentSettlement(
            key=f"{apartment_key}-{year}-{month}",
            apartment=apartment_key,
            year=year,
            month=month,
            total_due_pln=total_cost,
        )

    def create_tenants_settlements(
        self,
        apartment_settlement: ApartmentSettlement
    ) -> List[TenantSettlement] | None:
        if apartment_settlement is None:
            return None

        self._validate_month(apartment_settlement.month)

        if apartment_settlement.apartment not in self.apartments:
            return None

        tenants_in_apartment = [
            tenant
            for tenant in self.tenants.values()
            if tenant.apartment == apartment_settlement.apartment
        ]

        if not tenants_in_apartment:
            return []

        split_amount = (
            apartment_settlement.total_due_pln
            / len(tenants_in_apartment)
        )

        return [
            TenantSettlement(
                tenant=tenant.name,
                apartment_settlement=apartment_settlement.key,
                month=apartment_settlement.month,
                year=apartment_settlement.year,
                total_due_pln=split_amount,
            )
            for tenant in tenants_in_apartment
        ]

    def get_debtors(
        self,
        apartment_key: str,
        year: int,
        month: int
    ) -> List[str]:
        self._validate_month(month)

        settlement = self.get_settlement(
            apartment_key,
            year,
            month
        )

        if settlement is None:
            return []

        tenant_settlements = self.create_tenants_settlements(settlement)

        if tenant_settlements is None:
            return []

        output = []

        for tenant_settlement in tenant_settlements:
            tenant_transfers = [
                transfer
                for transfer in self.transfers
                if self.tenants[transfer.tenant].name
                == tenant_settlement.tenant
                and transfer.settlement_year == year
                and transfer.settlement_month == month
            ]

            total_paid = sum(
                transfer.amount_pln
                for transfer in tenant_transfers
            )

            if total_paid < tenant_settlement.total_due_pln:
                output.append(tenant_settlement.tenant)

        return output

    def calculate_tax(
        self,
        year: int,
        month: int,
        tax_rate: float
    ) -> float:
        total_income = sum(
            transfer.amount_pln
            for transfer in self.transfers
            if transfer.settlement_year == year
            and transfer.settlement_month == month
        )

        return round(total_income * tax_rate, 0)

    def check_deposits(self) -> float:
        total_deposits = 0.0
        total_due = 0.0

        for tenant in self.tenants.values():
            total_deposits += sum(
                transfer.amount_pln
                for transfer in self.transfers
                if self.tenants[transfer.tenant].name == tenant.name
                and transfer.type == "deposit"
            )

            total_due += tenant.deposit_pln

        return total_deposits - total_due

    def get_annual_balance(self, year: int) -> float:
        total_income = sum(
            transfer.amount_pln
            for transfer in self.transfers
            if transfer.settlement_year == year
        )

        total_due = sum(
            bill.amount_pln
            for bill in self.bills
            if bill.settlement_year == year
        )

        return total_income - total_due

    def has_any_bills(
        self,
        apartment_key: str,
        year: int,
        month: int
    ) -> bool:
        self._validate_month(month)

        if apartment_key not in self.apartments:
            raise ValueError("Apartment key does not exist")

        return any(
            bill.apartment == apartment_key
            and bill.settlement_year == year
            and bill.settlement_month == month
            for bill in self.bills
        )

    def check_transfers_amount_range(self) -> bool:
        return all(
            -self.parameters.max_refund_pln
            <= transfer.amount_pln
            <= self.parameters.max_transfer_pln
            for transfer in self.transfers
        )

    def check_tenant_blacklist(self, tenant_name: str) -> bool:
        return any(
            entry.tenant == tenant_name
            for entry in self.tenants_blacklist
        )

    def check_transfers_tenant(self) -> bool:
        for transfer in self.transfers:
            if transfer.tenant not in self.tenants:
                return False

            if (
                transfer.settlement_year is not None
                and transfer.settlement_month is not None
            ):
                tenant = self.tenants[transfer.tenant]

                agreement_from = datetime.strptime(
                    tenant.date_agreement_from,
                    "%Y-%m-%d"
                ).date()

                agreement_to = datetime.strptime(
                    tenant.date_agreement_to,
                    "%Y-%m-%d"
                ).date()

                transfer_date = date(
                    transfer.settlement_year,
                    transfer.settlement_month,
                    1
                )

                if not (
                    agreement_from
                    <= transfer_date
                    <= agreement_to
                ):
                    return False

        return True