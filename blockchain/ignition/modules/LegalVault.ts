import { buildModule } from "@nomicfoundation/hardhat-ignition/modules";

export default buildModule("LegalVaultModule", (m) => {
  const legalVault = m.contract("LegalVault");

  return { legalVault };
});