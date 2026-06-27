//! AI Proof Registry — Casper Agentic Buildathon 2026
//!
//! Stores immutable proof records for BotNesia AI agent business decisions.
//! Every AI-driven action (hiring recommendation, price change, workflow trigger)
//! is hashed and stored on-chain for auditability and accountability.
//!
//! Deploy:
//!   cargo build --release --target wasm32-unknown-unknown
//!   casper-client put-deploy \
//!     --session-path target/wasm32-unknown-unknown/release/ai_proof_registry.wasm \
//!     --session-arg "op:String='install'" \
//!     --chain-name casper-test
//!
//! Deployed contract on Casper Testnet:
//!   Contract hash:         15009cd4a6489c904b699c0a1f292e7e5557e823e54c236539c9ce9973ee2323
//!   Contract package hash: 897c4bd670325c1f17ab1704633a470f55eeeb1ec2b357ef48e5d26ecb78a9f0
//!   Explorer: https://testnet.cspr.live/contract-package/897c4bd670325c1f17ab1704633a470f55eeeb1ec2b357ef48e5d26ecb78a9f0

#![no_std]
#![no_main]

extern crate alloc;

use alloc::string::String;
use casper_contract::{
    contract_api::{runtime, storage},
    unwrap_or_revert::UnwrapOrRevert,
};
use casper_types::{CLType, EntryPoint, EntryPointAccess, EntryPointType, EntryPoints, Parameter, U64};

const ENTRY_STORE_PROOF: &str = "store_proof";
const ENTRY_GET_PROOF: &str = "get_proof";

const ARG_SESSION_HASH: &str = "session_hash";
const ARG_AI_ACTION_HASH: &str = "ai_action_hash";
const ARG_WORKFLOW_HASH: &str = "workflow_hash";
const ARG_INVOICE_HASH: &str = "invoice_hash";
const ARG_APPROVAL_HASH: &str = "approval_hash";
const ARG_TIMESTAMP: &str = "timestamp";

/// Install entry point — called once during initial deployment.
/// Creates the contract and registers entry points.
#[no_mangle]
pub extern "C" fn install() {
    let entry_points = {
        let mut eps = EntryPoints::new();
        eps.add_entry_point(EntryPoint::new(
            ENTRY_STORE_PROOF,
            alloc::vec![
                Parameter::new(ARG_SESSION_HASH, CLType::String),
                Parameter::new(ARG_AI_ACTION_HASH, CLType::String),
                Parameter::new(ARG_WORKFLOW_HASH, CLType::String),
                Parameter::new(ARG_INVOICE_HASH, CLType::String),
                Parameter::new(ARG_APPROVAL_HASH, CLType::String),
                Parameter::new(ARG_TIMESTAMP, CLType::U64),
            ],
            CLType::Unit,
            EntryPointAccess::Public,
            EntryPointType::Contract,
        ));
        eps.add_entry_point(EntryPoint::new(
            ENTRY_GET_PROOF,
            alloc::vec![Parameter::new(ARG_SESSION_HASH, CLType::String)],
            CLType::Option(alloc::boxed::Box::new(CLType::String)),
            EntryPointAccess::Public,
            EntryPointType::Contract,
        ));
        eps
    };
    let (contract_hash, _version) = storage::new_contract(
        entry_points,
        None,
        Some(String::from("ai_proof_registry_package")),
        Some(String::from("ai_proof_registry_access")),
    );
    runtime::put_key("ai_proof_registry", contract_hash.into());
}

/// store_proof entry point.
/// Stores the 6-field proof record as a JSON string under the key
/// "proof:{session_hash}" in the contract's named keys.
#[no_mangle]
pub extern "C" fn store_proof() {
    let session_hash: String = runtime::get_named_arg(ARG_SESSION_HASH);
    let ai_action_hash: String = runtime::get_named_arg(ARG_AI_ACTION_HASH);
    let workflow_hash: String = runtime::get_named_arg(ARG_WORKFLOW_HASH);
    let invoice_hash: String = runtime::get_named_arg(ARG_INVOICE_HASH);
    let approval_hash: String = runtime::get_named_arg(ARG_APPROVAL_HASH);
    let timestamp: U64 = runtime::get_named_arg(ARG_TIMESTAMP);

    let value = alloc::format!(
        r#"{{"session_hash":"{}","ai_action_hash":"{}","workflow_hash":"{}","invoice_hash":"{}","approval_hash":"{}","timestamp":{}}}"#,
        session_hash, ai_action_hash, workflow_hash, invoice_hash, approval_hash, timestamp,
    );

    let storage_key = alloc::format!("proof:{}", session_hash);
    let uref = storage::new_uref(value);
    runtime::put_key(&storage_key, uref.into());
}

/// get_proof entry point.
/// Returns the stored proof JSON string for a given session_hash, if any.
#[no_mangle]
pub extern "C" fn get_proof() {
    let session_hash: String = runtime::get_named_arg(ARG_SESSION_HASH);
    let storage_key = alloc::format!("proof:{}", session_hash);
    if let Some(key) = runtime::get_key(&storage_key) {
        let uref = key.into_uref().unwrap_or_revert();
        let value: String = storage::read(uref).unwrap_or_revert().unwrap_or_revert();
        runtime::ret(casper_types::CLValue::from_t(Some(value)).unwrap_or_revert());
    } else {
        runtime::ret(
            casper_types::CLValue::from_t::<Option<String>>(None).unwrap_or_revert(),
        );
    }
}

#[no_mangle]
pub extern "C" fn call() {
    install();
}
