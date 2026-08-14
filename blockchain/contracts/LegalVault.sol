// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract LegalVault {

    struct Document {
        string documentId;
        string documentHash;
        address owner;
        uint256 timestamp;
        uint256 version;
    }

    mapping(string => Document) private documents;

    function registerDocument(
        string memory _documentId,
        string memory _documentHash,
        uint256 _version
    ) public {
        documents[_documentId] = Document(
            _documentId,
            _documentHash,
            msg.sender,
            block.timestamp,
            _version
        );
    }

    function getDocument(
        string memory _documentId
    ) public view returns (
        string memory,
        string memory,
        address,
        uint256,
        uint256
    ) {
        Document memory doc = documents[_documentId];

        return (
            doc.documentId,
            doc.documentHash,
            doc.owner,
            doc.timestamp,
            doc.version
        );
    }
}