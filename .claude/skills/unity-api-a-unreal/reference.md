# Referencia Unity → Unreal Engine 5.8

Notación: `Owner` = `GetOwner()` (AActor*). Los helpers marcados con † existen en la capa
`UnityCompat` generada por unity2ue (`UUnityBehaviour`, `UUnityCompatLibrary`).

## GameObject / Transform

| Unity | Unreal Engine 5.8 |
|---|---|
| `gameObject` | `GetOwner()` († `GetGameObject()`) |
| `transform` | `Owner->GetRootComponent()` († `GetTransform()`) |
| `transform.position` / `= v` | `Owner->GetActorLocation()` / `Owner->SetActorLocation(v)` |
| `transform.localPosition` | `GetTransform()->GetRelativeLocation()` / `SetRelativeLocation()` |
| `transform.rotation` | `Owner->GetActorQuat()` / `GetActorRotation()` |
| `transform.eulerAngles` | `Owner->GetActorRotation()` (FRotator: Pitch, Yaw, Roll) |
| `transform.localScale` | `GetTransform()->GetRelativeScale3D()` |
| `transform.forward/right/up` | `Owner->GetActorForwardVector()/GetActorRightVector()/GetActorUpVector()` |
| `transform.Translate(v)` (local) | `Owner->AddActorLocalOffset(v * 100)` |
| `transform.Translate(v, Space.World)` | `Owner->AddActorWorldOffset(v * 100)` |
| `transform.Rotate(axis, deg)` | `Owner->AddActorLocalRotation(FQuat(Axis, FMath::DegreesToRadians(Deg)))` |
| `transform.LookAt(t)` | `Owner->SetActorRotation((T - Loc).Rotation())` o `UKismetMathLibrary::FindLookAtRotation` |
| `transform.parent` / `SetParent(p)` | `Owner->GetAttachParentActor()` / `AttachToActor(P, FAttachmentTransformRules::KeepWorldTransform)` |
| `transform.childCount` / `GetChild(i)` | `Owner->GetAttachedActors(Out)` |
| `transform.TransformPoint(p)` | `Owner->GetActorTransform().TransformPosition(p)` |
| `transform.InverseTransformPoint(p)` | `Owner->GetActorTransform().InverseTransformPosition(p)` |
| `GetComponent<T>()` | `Owner->FindComponentByClass<T>()` († `GetComponent<T>()`) |
| `GetComponents<T>()` | `Owner->GetComponents<T>(Array)` († `GetComponents<T>()`) |
| `GetComponentInChildren<T>()` | recorrer `GetAttachedActors` + `FindComponentByClass`, o `Owner->GetComponents` |
| `AddComponent<T>()` | `NewObject<T>(Owner)` + `RegisterComponent()` (+ `AttachToComponent` si es scene) |
| `gameObject.SetActive(b)` | `Owner->SetActorHiddenInGame(!b); SetActorEnableCollision(b); SetActorTickEnabled(b)` († `AUnityGameObject::SetActive`) |
| `activeSelf` | `!Owner->IsHidden()` |
| `enabled = b` (componente) | `SetActive(b)` / † `SetEnabled(b)` |
| `CompareTag("X")` / `tag` | `Owner->ActorHasTag("X")` († `CompareTag`) / `Owner->Tags` |
| `name` | `Owner->GetActorNameOrLabel()` / `GetName()` |
| `layer` | tag `Layer:<nombre>` o canal de colisión (`ECC_GameTraceChannelN`) |
| `Instantiate(prefab, pos, rot)` | `GetWorld()->SpawnActor<AActor>(Class, Pos, Rot, Params)` († `Instantiate`) |
| `Destroy(go)` / `Destroy(go, t)` | `Actor->Destroy()` / `Actor->SetLifeSpan(t)` († `DestroyActor`) |
| `Destroy(component)` | `Comp->DestroyComponent()` |
| `DontDestroyOnLoad` | mover estado a `UGameInstance` / `UGameInstanceSubsystem` |
| `GameObject.Find("n")` | † `UUnityCompatLibrary::FindByName` (mejor: referencia UPROPERTY) |
| `FindWithTag` / `FindGameObjectsWithTag` | `UGameplayStatics::GetAllActorsWithTag` († helpers) |
| `FindObjectOfType<T>()` | `UGameplayStatics::GetActorOfClass(this, T::StaticClass())` o `TActorIterator<T>` |
| `SendMessage("F")` | interfaz UINTERFACE o delegado; evitar reflexión por nombre |

## Tiempo y ciclo de vida

| Unity | Unreal |
|---|---|
| `Time.deltaTime` | parámetro `DeltaTime` de `Update` / `GetWorld()->GetDeltaSeconds()` |
| `Time.fixedDeltaTime` | `FixedDeltaTime` († miembro de UUnityBehaviour) |
| `Time.time` | `GetWorld()->GetTimeSeconds()` |
| `Time.unscaledTime` | `GetWorld()->GetRealTimeSeconds()` |
| `Time.timeScale = s` | `UGameplayStatics::SetGlobalTimeDilation(this, s)` |
| `Time.frameCount` | `GFrameCounter` |
| `StartCoroutine(C())` + `yield return new WaitForSeconds(t)` | `GetWorld()->GetTimerManager().SetTimer(Handle, this, &U::Fn, t, false)` († `InvokeAfter`) |
| `yield return null` (siguiente frame) | `GetWorld()->GetTimerManager().SetTimerForNextTick(...)` |
| `InvokeRepeating("F", d, r)` | `SetTimer(Handle, this, &U::F, r, true, d)` († `InvokeRepeating`) |
| `CancelInvoke` / `StopCoroutine` | `GetWorld()->GetTimerManager().ClearTimer(Handle)` |
| `Application.Quit()` | `UKismetSystemLibrary::QuitGame(this, nullptr, EQuitPreference::Quit, false)` |

## Matemáticas

| Unity | Unreal |
|---|---|
| `Vector3` / `Vector2` / `Quaternion` | `FVector` / `FVector2D` / `FQuat` (o `FRotator`) |
| `Vector3.zero/one/up/forward/right` | `FVector::ZeroVector/OneVector/UpVector/ForwardVector/RightVector` |
| `Vector3.Distance(a,b)` | `FVector::Dist(A, B)` (¡en cm!) |
| `Vector3.Lerp` / `Mathf.Lerp` | `FMath::Lerp` |
| `Vector3.MoveTowards` | `FMath::VInterpConstantTo(Cur, Target, DeltaTime, Speed)` |
| `Vector3.SmoothDamp` | `FMath::VInterpTo` (aprox.) o `UKismetMathLibrary::VectorSpringInterp` |
| `v.normalized` / `v.magnitude` / `sqrMagnitude` | `V.GetSafeNormal()` / `V.Size()` / `V.SizeSquared()` |
| `Vector3.Dot/Cross` | `FVector::DotProduct / CrossProduct` |
| `Vector3.Angle(a,b)` | `FMath::RadiansToDegrees(FMath::Acos(FVector::DotProduct(A.GetSafeNormal(), B.GetSafeNormal())))` |
| `Quaternion.Euler(x,y,z)` | `FRotator(-X, Y, -Z).Quaternion()` (revisar signos según uso) |
| `Quaternion.LookRotation(f)` | `FRotationMatrix::MakeFromX(F).ToQuat()` |
| `Quaternion.Slerp` | `FQuat::Slerp` |
| `Mathf.Clamp/Clamp01/Abs/Sign/Min/Max` | `FMath::Clamp / FMath::Clamp(x,0.f,1.f) / FMath::Abs / FMath::Sign / FMath::Min / FMath::Max` |
| `Mathf.Sin/Cos/Atan2/Sqrt/Pow` | `FMath::Sin/Cos/Atan2/Sqrt/Pow` |
| `Mathf.Deg2Rad` / `Rad2Deg` | `FMath::DegreesToRadians` / `FMath::RadiansToDegrees` |
| `Mathf.PingPong / Repeat` | `FMath::Fmod` + lógica / `FMath::Wrap` |
| `Mathf.MoveTowards` | † `UUnityCompatLibrary::MoveTowards` |
| `Mathf.Approximately(a,b)` | `FMath::IsNearlyEqual(A, B)` |
| `Random.Range(a,b)` float / int | `FMath::FRandRange(A,B)` / `FMath::RandRange(A, B-1)` (máx. exclusivo en Unity) |
| `Random.value` | `FMath::FRand()` |
| `Random.insideUnitSphere` | `FMath::VRand() * FMath::FRand()` |

## Física

| Unity | Unreal |
|---|---|
| `Rigidbody` | `UPrimitiveComponent` raíz con `SetSimulatePhysics(true)` |
| `rb.AddForce(f)` (Force) | `Prim->AddForce(F)` |
| `rb.AddForce(f, ForceMode.Impulse)` | `Prim->AddImpulse(F)` |
| `ForceMode.VelocityChange` | `Prim->AddImpulse(F, NAME_None, true)` |
| `ForceMode.Acceleration` | `Prim->AddForce(F, NAME_None, true)` |
| `rb.AddTorque` | `Prim->AddTorqueInDegrees / AddTorqueInRadians` |
| `rb.velocity` / `linearVelocity` | `Prim->GetPhysicsLinearVelocity()` / `SetPhysicsLinearVelocity()` |
| `rb.angularVelocity` | `GetPhysicsAngularVelocityInRadians()` |
| `rb.isKinematic = b` | `Prim->SetSimulatePhysics(!b)` |
| `rb.useGravity` | `Prim->SetEnableGravity(b)` |
| `rb.mass` | `Prim->GetMass()` / `SetMassOverrideInKg(NAME_None, M)` |
| `rb.MovePosition(p)` | `Prim->SetWorldLocation(P, true)` (sweep) |
| `Physics.Raycast(o, d, out hit, dist)` | `GetWorld()->LineTraceSingleByChannel(Hit, O, O + D * Dist*100, ECC_Visibility, Params)` |
| `Physics.RaycastAll` | `LineTraceMultiByChannel` |
| `Physics.SphereCast` | `SweepSingleByChannel(..., FCollisionShape::MakeSphere(R*100))` |
| `Physics.OverlapSphere` | `OverlapMultiByChannel(..., FCollisionShape::MakeSphere(R*100))` |
| `RaycastHit.point/normal/collider/distance` | `Hit.ImpactPoint / ImpactNormal / GetComponent() / Distance` |
| `LayerMask` | canales de colisión / `FCollisionObjectQueryParams` / perfiles de colisión |
| `OnTriggerEnter(Collider c)` | † `OnTriggerEnter(AActor* Other)` (overlap; componente con `GenerateOverlapEvents`) |
| `OnCollisionEnter(Collision c)` | † `OnCollisionEnter(AActor* Other, const FHitResult& Hit)` (requiere `SetNotifyRigidBodyCollision(true)`) |
| `c.gameObject` | `Other` |
| `CharacterController.Move(v)` | `ACharacter` + `UCharacterMovementComponent::AddInputVector` o `Pawn->AddMovementInput` |
| `CharacterController.isGrounded` | `GetCharacterMovement()->IsMovingOnGround()` |

## Input

| Unity | Unreal (Enhanced Input) |
|---|---|
| `Input.GetAxis("Horizontal")` | `UInputAction` `IA_Horizontal` (Axis1D) enlazada con `BindAction(..., ETriggerEvent::Triggered, ...)`; guardar `Value.Get<float>()` |
| `Input.GetButtonDown("Jump")` | `IA_Jump` con `ETriggerEvent::Started` |
| `Input.GetButton` / `GetButtonUp` | `ETriggerEvent::Triggered` / `ETriggerEvent::Completed` |
| `Input.GetKeyDown(KeyCode.Space)` | `PlayerController->WasInputKeyJustPressed(EKeys::SpaceBar)` (rápido) o acción |
| `Input.mousePosition` | `PlayerController->GetMousePosition(X, Y)` |
| `Input.GetMouseButtonDown(0)` | `WasInputKeyJustPressed(EKeys::LeftMouseButton)` |
| Registro del contexto | `UEnhancedInputLocalPlayerSubsystem::AddMappingContext(IMC_UnityDefault, 0)` |
| `Cursor.lockState` | `PlayerController->SetInputMode(FInputModeGameOnly())`, `bShowMouseCursor` |

## Cámara

| Unity | Unreal |
|---|---|
| `Camera.main` | `UGameplayStatics::GetPlayerCameraManager(this, 0)` / cámara del Pawn |
| `camera.fieldOfView` (vertical) | `UCameraComponent::FieldOfView` (horizontal: `2·atan(tan(v/2)·aspect)`) |
| `ScreenToWorldPoint` / `ScreenPointToRay` | `PlayerController->DeprojectScreenPositionToWorld` |
| `WorldToScreenPoint` | `PlayerController->ProjectWorldLocationToScreen` |
| Cinemachine | `USpringArmComponent` + `UCameraComponent`, `SetViewTargetWithBlend` |

## Audio

| Unity | Unreal |
|---|---|
| `AudioSource.Play()` / `Stop()` | `UAudioComponent::Play()` / `Stop()` |
| `AudioSource.PlayOneShot(clip)` | `UGameplayStatics::PlaySound2D(this, Sound)` o `SpawnSoundAttached` |
| `AudioSource.PlayClipAtPoint(clip, p)` | `UGameplayStatics::PlaySoundAtLocation(this, Sound, P)` |
| `volume` / `pitch` | `SetVolumeMultiplier` / `SetPitchMultiplier` |
| `AudioClip` | `USoundBase` (`USoundWave`, `USoundCue`, MetaSounds) |

## Animación

| Unity | Unreal |
|---|---|
| `Animator` | `USkeletalMeshComponent` + `UAnimInstance` (Animation Blueprint) |
| `animator.SetFloat/SetBool/SetInteger("p", v)` | variable en el AnimInstance: `Cast<UMyAnimInstance>(Mesh->GetAnimInstance())->P = V` |
| `animator.SetTrigger("t")` | bool de un frame en el AnimInstance o `Montage_Play` |
| `animator.Play("State")` | `AnimInstance->Montage_Play(Montage)` o `Mesh->PlayAnimation(Seq, bLoop)` |
| `Animation.Play(clip)` (legacy) | `Mesh->PlayAnimation(AnimSequence, bLoop)` |

## UI

| Unity | Unreal (UMG) |
|---|---|
| `Canvas` | `UUserWidget` (`CreateWidget<UUserWidget>(PC, Class)->AddToViewport()`) |
| `Text` / `TMP_Text.text = s` | `UTextBlock::SetText(FText::FromString(S))` |
| `Image.sprite` / `color` | `UImage::SetBrushFromTexture` / `SetColorAndOpacity` |
| `Button.onClick.AddListener(f)` | `Button->OnClicked.AddDynamic(this, &U::F)` (UFUNCTION) |
| `Slider.value` | `USlider::GetValue/SetValue` |
| `EventSystem` | gestionado por Slate/UMG (`SetInputMode(FInputModeUIOnly())`) |

## Escenas, datos y utilidades

| Unity | Unreal |
|---|---|
| `SceneManager.LoadScene("n")` | `UGameplayStatics::OpenLevel(this, "n")` († `LoadScene`) |
| Carga aditiva | `ULevelStreaming` / `UGameplayStatics::LoadStreamLevel` / World Partition |
| `PlayerPrefs` | `USaveGame` + `UGameplayStatics::SaveGameToSlot/LoadGameFromSlot` |
| `ScriptableObject` | `UPrimaryDataAsset` (instancias como assets de datos) |
| `Resources.Load<T>("p")` | `TSoftObjectPtr<T>` + `LoadSynchronous()` o `StaticLoadObject` |
| `JsonUtility` | `FJsonObjectConverter::UStructToJsonObjectString` / `JsonObjectStringToUStruct` |
| `Debug.Log/LogWarning/LogError` | `UE_LOG(LogUnity, Log/Warning/Error, TEXT("..."))` († `UNITY_LOG*`) |
| `Debug.DrawLine/DrawRay` | `DrawDebugLine(GetWorld(), A, B, FColor::Red, false, T)` (`DrawDebugHelpers.h`) |
| `UnityEvent` | `FUnityEvent` († delegado dinámico multicast) / `DECLARE_DYNAMIC_MULTICAST_DELEGATE_*` |
| `event Action<T>` / `System.Action` | `DECLARE_MULTICAST_DELEGATE_OneParam` / `TFunction<void()>` |
| `List<T>` / `Dictionary<K,V>` / `HashSet<T>` | `TArray<T>` / `TMap<K,V>` / `TSet<T>` |
| `list.Count` / `Add` / `Remove` / `Contains` | `Num()` / `Add` / `Remove` / `Contains` |
| `string.Format` / interpolación `$""` | `FString::Printf(TEXT("%s %d"), *S, N)` |
| `int.Parse` / `ToString()` | `FCString::Atoi(*S)` / `FString::FromInt`, `FString::SanitizeFloat` |
| LINQ `Where/Select/Any/First` | `FilterByPredicate` / bucle / `ContainsByPredicate` / `FindByPredicate` |
| `foreach (var x in list)` | `for (auto& X : List)` |
| `#if UNITY_EDITOR` | `#if WITH_EDITOR` |
| `[SerializeField] private` | `UPROPERTY(EditAnywhere, meta=(AllowPrivateAccess="true"))` |
| `[Header("X")]` / `[Range(a,b)]` / `[Tooltip]` | `Category="X"` / `meta=(ClampMin, ClampMax)` / `meta=(ToolTip)` |
| `[RequireComponent(typeof(T))]` | crear el componente en el Blueprint/constructor del actor |
| `NavMeshAgent.SetDestination(p)` | `UAIBlueprintHelperLibrary::SimpleMoveToLocation(Controller, P)` / `AAIController::MoveToLocation` |
