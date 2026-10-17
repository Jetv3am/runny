import SwiftUI

struct ContentView: View {
    // IMPORTANT: Replace the URL with your development computer's LAN IP address,
    // not 127.0.0.1. Replace the token with the same SYNC_API_TOKEN from the backend .env.
    @StateObject private var sync = HealthKitSyncManager(
        apiBaseURL: URL(string: "http://192.168.1.100:8000")!,
        apiToken: "replace-with-the-same-long-random-token"
    )

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "figure.run")
                .font(.system(size: 44))
            Text("Running Coach")
                .font(.title.bold())
            Text(sync.status)
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            Button("Connect Apple Health") {
                Task { await sync.connectAndStart() }
            }
            .buttonStyle(.borderedProminent)
        }
        .padding(28)
        .task {
            // On later launches, re-establish the observer so background delivery can resume.
            await sync.connectAndStart()
        }
    }
}
