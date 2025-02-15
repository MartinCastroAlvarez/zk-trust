// Deploy.sol
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.17;

import "forge-std/Script.sol";  // Import Foundry's standard library
import "./krates/verifier.sol"; // Import ZoKrates verifier contract

contract DeployScript is Script {
    function run() external {
        vm.startBroadcast(); // Allows transaction broadcasting
        Verifier verifier = new Verifier();
        vm.stopBroadcast();
        
        console.log("Verifier deployed at:", address(verifier)); // This now works
    }
}
