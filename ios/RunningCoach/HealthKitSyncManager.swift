import Combine
import Foundation
import HealthKit

/// Reads new running workouts from Apple Health and sends them to the FastAPI backend.
/// Add this file to a native iOS SwiftUI app created in Xcode.
@MainActor
final class HealthKitSyncManager: ObservableObject {
    @Published private(set) var status = "Not connected"

    private let healthStore = HKHealthStore()
    private let apiBaseURL: URL
    private let apiToken: String
    private let anchorKey = "runningCoach.healthKitWorkoutAnchor.v1"
    private var observerQuery: HKObserverQuery?
    private var isStarted = false

    init(apiBaseURL: URL, apiToken: String) {
        self.apiBaseURL = apiBaseURL
        self.apiToken = apiToken
    }

    func connectAndStart() async {
        guard HKHealthStore.isHealthDataAvailable() else {
            status = "HealthKit is unavailable on this device."
            return
        }

        let workoutType = HKObjectType.workoutType()

        do {
            try await healthStore.requestAuthorization(toShare: [], read: [workoutType])
            try await healthStore.enableBackgroundDelivery(for: workoutType, frequency: .immediate)
            startObserverIfNeeded(workoutType: workoutType)
            status = "Connected. Syncing new runs from Apple Health."
            // A first sync also catches workouts saved before the observer was installed.
            fetchNewWorkouts(completion: {})
        } catch {
            status = "HealthKit setup failed: \(error.localizedDescription)"
        }
    }

    private func startObserverIfNeeded(workoutType: HKWorkoutType) {
        guard !isStarted else { return }
        isStarted = true

        let observer = HKObserverQuery(sampleType: workoutType, predicate: nil) { [weak self] _, completion, error in
            guard let self else {
                completion()
                return
            }

            if let error {
                Task { @MainActor in
                    self.status = "HealthKit observer error: \(error.localizedDescription)"
                    completion()
                }
                return
            }

            Task { @MainActor in
                self.fetchNewWorkouts(completion: completion)
            }
        }
        observerQuery = observer
        healthStore.execute(observer)
    }

    /// Observer queries only notify us that the store changed. The anchored query
    /// returns the actual new workouts and lets us persist a sync checkpoint.
    private func fetchNewWorkouts(completion: @escaping () -> Void) {
        let oldAnchor: HKQueryAnchor? = {
            guard let data = UserDefaults.standard.data(forKey: anchorKey) else { return nil }
            return try? NSKeyedUnarchiver.unarchivedObject(ofClass: HKQueryAnchor.self, from: data)
        }()

        let query = HKAnchoredObjectQuery(
            type: HKObjectType.workoutType(),
            predicate: nil,
            anchor: oldAnchor,
            limit: HKObjectQueryNoLimit
        ) { [weak self] _, samples, _, newAnchor, error in
            guard let self else {
                completion()
                return
            }
            guard error == nil, let newAnchor else {
                Task { @MainActor in
                    self.status = "Could not read new workouts: \(error?.localizedDescription ?? "unknown error")"
                    completion()
                }
                return
            }

            let runs = (samples as? [HKWorkout] ?? []).filter { $0.workoutActivityType == .running }
            Task { @MainActor in
                let uploadSucceeded = await self.upload(runs)
                // Do not advance the anchor when upload fails; the next sync can retry.
                if uploadSucceeded {
                    do {
                        let data = try NSKeyedArchiver.archivedData(withRootObject: newAnchor, requiringSecureCoding: true)
                        UserDefaults.standard.set(data, forKey: self.anchorKey)
                    } catch {
                        self.status = "Could not save sync checkpoint: \(error.localizedDescription)"
                    }
                }
                completion()
            }
        }
        healthStore.execute(query)
    }

    private func upload(_ workouts: [HKWorkout]) async -> Bool {
        guard !workouts.isEmpty else { return true }

        // Keep each request comfortably below the server's batch-size limit.
        let batchSize = 100
        for startIndex in stride(from: 0, to: workouts.count, by: batchSize) {
            let endIndex = min(startIndex + batchSize, workouts.count)
            let batch = Array(workouts[startIndex..<endIndex])
            let payload = WorkoutBatch(workouts: batch.map { workout in
                WorkoutPayload(
                    id: "healthkit_\(workout.uuid.uuidString.lowercased())",
                    startDate: workout.startDate,
                    endDate: workout.endDate,
                    distanceM: workout.totalDistance?.doubleValue(for: .meter()),
                    durationS: workout.endDate.timeIntervalSince(workout.startDate),
                    energyKcal: workout.totalEnergyBurned?.doubleValue(for: .kilocalorie()),
                    averageHeartrate: nil,
                    minimumHeartrate: nil,
                    maxHeartrate: nil,
                    sourceName: workout.sourceRevision.source.name
                )
            })

            do {
                let encoder = JSONEncoder()
                encoder.dateEncodingStrategy = .iso8601
                encoder.keyEncodingStrategy = .convertToSnakeCase
                let body = try encoder.encode(payload)

                let endpointURL = apiBaseURL
                    .appendingPathComponent("health")
                    .appendingPathComponent("workouts")
                    .appendingPathComponent("sync")
                var request = URLRequest(url: endpointURL)
                request.httpMethod = "POST"
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                request.setValue("Bearer \(apiToken)", forHTTPHeaderField: "Authorization")
                request.httpBody = body

                let (_, response) = try await URLSession.shared.data(for: request)
                guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                    await MainActor.run { self.status = "Sync failed. Check the API URL, token, and server logs." }
                    return false
                }
            } catch {
                await MainActor.run { self.status = "Upload failed: \(error.localizedDescription)" }
                return false
            }
        }

        await MainActor.run { self.status = "Synced \(workouts.count) new run(s)." }
        return true
    }
}

private struct WorkoutBatch: Encodable {
    let workouts: [WorkoutPayload]
}

private struct WorkoutPayload: Encodable {
    let id: String
    let startDate: Date
    let endDate: Date
    let distanceM: Double?
    let durationS: Double
    let energyKcal: Double?
    let averageHeartrate: Double?
    let minimumHeartrate: Double?
    let maxHeartrate: Double?
    let sourceName: String
}
